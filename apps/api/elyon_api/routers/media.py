from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from typing import Any

from fastapi import APIRouter, Depends, Form, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from elyon_api.db import get_db
from elyon_api.deps import (
    audit,
    get_device_from_request,
    require_permission,
    require_same_org,
    require_site_access,
)
from elyon_api.models import (
    Command,
    CommandStatus,
    CommandType,
    Device,
    DeviceStatus,
    Media,
    MediaKind,
    MediaStatus,
    Organization,
    Playlist,
    PlaylistItem,
    Role,
    Team,
    User,
)
from elyon_api.permissions import Permission
from elyon_api.schemas import (
    MediaOut,
    MediaRename,
    MediaShowRequest,
    TeamShareIn,
)
from elyon_api.services.storage import build_storage, safe_storage_path

router = APIRouter(prefix="/api/media", tags=["media"])

_EXT_KIND = {
    ".mp4": MediaKind.VIDEO,
    ".webm": MediaKind.VIDEO,
    ".mkv": MediaKind.VIDEO,
    ".mov": MediaKind.VIDEO,
    ".avi": MediaKind.VIDEO,
    ".jpg": MediaKind.IMAGE,
    ".jpeg": MediaKind.IMAGE,
    ".png": MediaKind.IMAGE,
    ".gif": MediaKind.IMAGE,
    ".webp": MediaKind.IMAGE,
    ".bmp": MediaKind.IMAGE,
    ".svg": MediaKind.IMAGE,
    ".tif": MediaKind.IMAGE,
    ".tiff": MediaKind.IMAGE,
    ".heic": MediaKind.IMAGE,
    ".heif": MediaKind.IMAGE,
    ".pdf": MediaKind.PDF,
    ".pptx": MediaKind.OFFICE,
    ".ppt": MediaKind.OFFICE,
    ".odp": MediaKind.OFFICE,
    ".docx": MediaKind.OFFICE,
    ".doc": MediaKind.OFFICE,
    ".odt": MediaKind.OFFICE,
    ".xlsx": MediaKind.OFFICE,
    ".xls": MediaKind.OFFICE,
    ".ods": MediaKind.OFFICE,
}


def _kind_for(filename: str, content_type: str) -> MediaKind:
    ext = re.search(r"(\.[a-z0-9]+)$", filename.lower())
    if ext and ext.group(1) in _EXT_KIND:
        return _EXT_KIND[ext.group(1)]
    if content_type.startswith("video/"):
        return MediaKind.VIDEO
    if content_type.startswith("image/"):
        return MediaKind.IMAGE
    if content_type == "application/pdf":
        return MediaKind.PDF
    if content_type in (
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        "application/vnd.oasis.opendocument.presentation",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/msword",
        "application/vnd.oasis.opendocument.text",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.oasis.opendocument.spreadsheet",
    ):
        return MediaKind.OFFICE
    raise HTTPException(status_code=400, detail="Type de média non supporté")


@router.post("", status_code=201)
def upload_media(
    request: Request,
    file: UploadFile,
    name: str | None = None,
    org_id: str | None = Form(default=None),
    user: User = Depends(require_permission(Permission.MEDIA_UPLOAD)),
    db: Session = Depends(get_db),
) -> MediaOut:
    settings = request.app.state.settings
    if user.role != Role.SUPERADMIN:
        org = user.org_id
    else:
        org = org_id or db.scalar(select(Organization.id).order_by(Organization.name))
    if org is None:
        raise HTTPException(status_code=400, detail="Aucune organisation disponible")

    if user.role == Role.SUPERADMIN and db.get(Organization, org) is None:
        raise HTTPException(status_code=404, detail="Organisation introuvable")

    kind = _kind_for(file.filename or "", file.content_type or "")
    storage = build_storage(settings)
    sha = hashlib.sha256()
    total = 0
    import uuid as _uuid

    tmp_path = safe_storage_path(f"originals/{org}/.upload-{_uuid.uuid4().hex}")
    storage.delete(tmp_path)
    while True:
        chunk = file.file.read(1024 * 512)
        if not chunk:
            break
        total += len(chunk)
        if total > settings.max_media_bytes:
            storage.delete(tmp_path)
            raise HTTPException(status_code=413, detail="Fichier trop volumineux")
        sha.update(chunk)
        storage.append(tmp_path, chunk)
    if total == 0:
        storage.delete(tmp_path)
        raise HTTPException(status_code=400, detail="Fichier vide")
    rel_path = safe_storage_path(f"originals/{org}/{sha.hexdigest()}")
    if storage.exists(rel_path):
        storage.delete(tmp_path)
    else:
        storage.move(tmp_path, rel_path)
    _check_quota(db, user, settings, total, storage, rel_path)
    media = Media(
        org_id=org,
        user_id=user.id,
        team_id=user.team_id,
        name=name or (file.filename or "média"),
        original_filename=file.filename or "unknown",
        kind=kind,
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=total,
        sha256=sha.hexdigest(),
        storage_path=rel_path,
        status=MediaStatus.UPLOADED,
    )
    db.add(media)
    db.commit()
    db.refresh(media)
    audit(db, "media.upload", "media", media.id, detail=f"{kind.value} {total}", user=user)
    db.commit()
    if settings.enqueue_media_processing:
        from elyon_api.worker import process_media_task

        process_media_task.delay(media.id)
    elif settings.process_media_inline:
        from elyon_api.services.media_processing import process_media
        from elyon_api.services.storage import LocalStorage

        try:
            process_media(media, settings, LocalStorage(settings.media_storage_root))
            db.commit()
            db.refresh(media)
        except Exception as exc:  # noqa: BLE001 — un échec de conversion ne
            # doit pas invalider l'upload : le média reste consultable.
            db.rollback()
            media.status = MediaStatus.FAILED
            db.commit()
            db.refresh(media)
            import logging

            logging.getLogger("elyon.media").warning(
                "Traitement média %s échoué : %s", media.id, exc
            )
    return MediaOut.model_validate(media)


def _get_device(db: Session, user: User, device_id: str) -> Device:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Raspberry introuvable")
    require_site_access(db, user, device.org_id)
    return device


def _can_show_cross_org(db: Session, user: User, media: Media, device: Device) -> bool:
    """Autorise une diffusion inter-organisation quand l'utilisateur y a droit.

    - superadmin : contrôle la plateforme, pas de périmètre.
    - équipe partagée : le média appartient à l'équipe de l'utilisateur et le
      device est dans l'organisation de l'utilisateur.
    """
    if user.role == Role.SUPERADMIN:
        return True
    return (
        media.team_id is not None
        and media.team_id == user.team_id
        and user.org_id is not None
        and user.org_id == device.org_id
    )


@router.post("/{media_id}/show", status_code=201)
def show_media(
    media_id: str,
    body: MediaShowRequest,
    user: User = Depends(require_permission(Permission.DEVICE_COMMAND)),
    db: Session = Depends(get_db),
) -> dict:
    """Affiche immédiatement un média sur le Raspberry choisi.

    Sans `duration_seconds`, l'affichage est continu (le média reste à
    l'écran jusqu'au prochain « Afficher », « Arrêter la diffusion » ou
    resync du player).
    """
    media = _get_media(db, user, media_id)
    device = _get_device(db, user, body.device_id)
    if media.org_id != device.org_id and not _can_show_cross_org(db, user, media, device):
        raise HTTPException(
            status_code=400,
            detail="Média hors organisation de l'appareil — déplacez le média dans "
            "l'organisation de l'appareil ou choisissez un appareil de "
            "l'organisation du média",
        )
    if device.status != DeviceStatus.APPROVED:
        raise HTTPException(
            status_code=409,
            detail="Appareil indisponible (hors ligne, bloqué ou en maintenance)",
        )
    # Un seul show actif par appareil : on annule les shows précédents encore
    # en attente pour éviter les conflits d'ordre à la récupération.
    for stale in db.scalars(
        select(Command).where(
            Command.device_id == device.id,
            Command.type == CommandType.SHOW,
            Command.status == CommandStatus.PENDING,
        )
    ):
        stale.status = CommandStatus.FAILED
        stale.error = "Remplacé par une diffusion plus récente"
    payload: dict[str, str | int] = {
        "media_id": media.id,
        "name": media.name,
        "kind": media.kind.value,
    }
    if body.duration_seconds is not None:
        payload["duration_seconds"] = body.duration_seconds
    cmd = Command(
        device_id=device.id,
        type=CommandType.SHOW,
        payload=json.dumps(payload),
    )
    db.add(cmd)
    db.commit()
    db.refresh(cmd)
    audit(
        db,
        "media.show",
        "media",
        media.id,
        detail=f"device={device.id} {media.name}",
        user=user,
    )
    db.commit()
    return {"command_id": cmd.id, "device_id": device.id, "media_id": media.id}


@router.post("/{media_id}/stop-show", status_code=201)
def stop_show_media(
    media_id: str,
    body: MediaShowRequest,
    user: User = Depends(require_permission(Permission.DEVICE_COMMAND)),
    db: Session = Depends(get_db),
) -> dict:
    """Arrête la diffusion directe de ce média sur le Raspberry choisi.

    La commande est délivrée au player ; côté serveur on invalide aussi tout
    show en attente et on réinitialise l'état de lecture si c'était ce média
    qui était affiché (le mur reflète l'arrêt immédiatement, sans attendre le
    prochain heartbeat).
    """
    media = _get_media(db, user, media_id)
    device = _get_device(db, user, body.device_id)
    for stale in db.scalars(
        select(Command).where(
            Command.device_id == device.id,
            Command.type == CommandType.SHOW,
            Command.status == CommandStatus.PENDING,
        )
    ):
        stale.status = CommandStatus.FAILED
        stale.error = "Diffusion arrêtée"
    cmd = Command(
        device_id=device.id,
        type=CommandType.STOP_SHOW,
        payload=json.dumps({"media_id": media.id}),
    )
    db.add(cmd)
    if device.current_media_id == media.id:
        device.player_state = "idle"
        device.current_media_id = None
    from elyon_api.services.playback_state import mark_queue_stopped

    mark_queue_stopped(device.id)
    db.commit()
    db.refresh(cmd)
    audit(
        db,
        "media.stop_show",
        "media",
        media.id,
        detail=f"device={device.id}",
        user=user,
    )
    db.commit()
    return {"command_id": cmd.id, "device_id": device.id, "media_id": media.id}


@router.post("/{media_id}/playlists/{playlist_id}", status_code=201)
def add_media_to_playlist(
    media_id: str,
    playlist_id: str,
    user: User = Depends(require_permission(Permission.PLAYLIST_EDIT)),
    db: Session = Depends(get_db),
) -> dict:
    """Ajoute le média à la playlist choisie (fin de séquence)."""
    media = _get_media(db, user, media_id)
    playlist = db.get(Playlist, playlist_id)
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist introuvable")
    require_same_org(db, user, playlist.org_id)
    next_pos = (
        db.scalar(
            select(func.max(PlaylistItem.position)).where(
                PlaylistItem.playlist_id == playlist.id
            )
        )
        or 0
    )
    db.add(
        PlaylistItem(
            playlist_id=playlist.id,
            media_id=media.id,
            position=next_pos + 1,
        )
    )
    db.commit()
    audit(
        db,
        "playlist.add_item",
        "playlist",
        playlist.id,
        detail=media.id,
        user=user,
    )
    db.commit()
    return {"playlist_id": playlist.id, "media_id": media.id, "name": playlist.name}


def _media_scope(db: Session, user: User) -> list[Any]:
    """Périmètre de bibliothèque de l'utilisateur courant.

    - Membre d'une équipe → bibliothèque personnelle + fichiers de l'équipe ;
    - Sinon → ses propres médias (isolation stricte, superadmin inclus).
    """
    if user.team_id:
        return [
            (Media.user_id == user.id)
            | (Media.team_id == user.team_id)
        ]
    return [Media.user_id == user.id]


def _check_quota(
    db: Session, user: User, settings, new_bytes: int, storage, rel_path: str
) -> None:
    """Quota personnel ET équipe — le plafond applicable est le plus restrictif.

    0 = illimité. `settings.user_quota_bytes` (défaut historique 15 Go) borne
    les comptes sans quota explicite.
    """
    checks: list[tuple[int, str]] = []
    personal = user.quota_bytes or settings.user_quota_bytes
    used_self = db.scalar(
        select(func.coalesce(func.sum(Media.size_bytes), 0)).where(
            Media.user_id == user.id, Media.deleted_at.is_(None)
        )
    ) or 0
    checks.append((personal - used_self, "Quota de stockage personnel dépassé"))

    if user.team_id:
        team = db.get(Team, user.team_id)
        if team is not None and team.quota_bytes > 0:
            used_team = db.scalar(
                select(func.coalesce(func.sum(Media.size_bytes), 0)).where(
                    Media.team_id == team.id, Media.deleted_at.is_(None)
                )
            ) or 0
            checks.append(
                (team.quota_bytes - used_team, "Quota de stockage de l'équipe dépassé")
            )

    remaining = min((r for r, _ in checks), default=None)
    if remaining is not None and new_bytes > remaining:
        storage.delete(rel_path)
        base = next(
            (msg for r, msg in checks if r == remaining), "Quota de stockage dépassé"
        )
        # Guidance contextuelle : corbeille non vide → inviter à la vider.
        trashed = db.scalar(
            select(func.count()).select_from(Media).where(
                Media.user_id == user.id, Media.deleted_at.is_not(None)
            )
        ) or 0
        hint = (
            " Videz la corbeille pour libérer de l'espace."
            if trashed
            else " Supprimez d'anciens fichiers pour continuer."
        )
        raise HTTPException(status_code=413, detail=base + hint)


@router.get("")
def list_media(
    kind: MediaKind | None = None,
    status: MediaStatus | None = None,
    trash: bool = False,
    origin: str | None = None,
    user: User = Depends(require_permission(Permission.MEDIA_VIEW)),
    db: Session = Depends(get_db),
) -> list[MediaOut]:
    """Bibliothèque (corbeille exclue) ou corbeille (`?trash=true`).

    `origin=mine` : mes médias personnels (sans équipe).
    `origin=team` : les fichiers partagés par mon équipe.
    Sans filtre : les deux. Les médias corbeillés ne comptent pas dans les quotas.
    """
    scope = *_media_scope(db, user),
    if trash:
        stmt = select(Media).where(
            *scope, Media.deleted_at.is_not(None)
        ).order_by(Media.deleted_at.desc())
    else:
        stmt = select(Media).where(
            *scope, Media.deleted_at.is_(None)
        ).order_by(Media.created_at.desc())
    if origin == "mine":
        stmt = stmt.where(Media.team_id.is_(None))
    elif origin == "team":
        stmt = stmt.where(Media.team_id.is_not(None))
    if kind:
        stmt = stmt.where(Media.kind == kind)
    if status:
        stmt = stmt.where(Media.status == status)
    items = db.scalars(stmt).all()
    out: list[MediaOut] = []
    team_names: dict[str, str] = {}
    if user.team_id:
        team = db.get(Team, user.team_id)
        if team is not None:
            team_names[team.id] = team.name
    for m in items:
        item = MediaOut.model_validate(m)
        item.team_name = team_names.get(m.team_id or "")
        out.append(item)
    return out


def _get_media(db: Session, user: User, media_id: str) -> Media:
    """Média accessible par session : bibliothèque d'équipe ou fichiers propres.

    Aucun contournement (y compris superadmin hors équipe).
    """
    media = db.get(Media, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Média introuvable")
    if user.team_id:
        if media.team_id != user.team_id:
            raise HTTPException(status_code=404, detail="Média introuvable")
    elif media.user_id != user.id:
        raise HTTPException(status_code=404, detail="Média introuvable")
    return media


@router.post("/{media_id}/share", status_code=200)
def share_with_team(
    media_id: str,
    body: TeamShareIn,
    user: User = Depends(require_permission(Permission.MEDIA_EDIT)),
    db: Session = Depends(get_db),
) -> MediaOut:
    """Partage un média personnel avec une équipe (il devient visible d'elle).

    Seul le propriétaire peut partager. Le média rejoint la bibliothèque de
    l'équipe : son quota d'équipe s'applique désormais.
    """
    media = _get_media(db, user, media_id)
    if media.team_id is not None:
        raise HTTPException(status_code=409, detail="Média déjà partagé")
    team = db.get(Team, body.team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Équipe introuvable")
    if team.id != user.team_id:
        raise HTTPException(status_code=403, detail="Vous ne pouvez partager qu'avec votre équipe")
    media.team_id = team.id
    db.commit()
    db.refresh(media)
    audit(db, "media.share", "media", media.id, detail=team.name, user=user)
    db.commit()
    out = MediaOut.model_validate(media)
    out.team_name = team.name
    return out


@router.get("/quota")
def media_quota(
    request: Request,
    user: User = Depends(require_permission(Permission.MEDIA_VIEW)),
    db: Session = Depends(get_db),
) -> dict:
    """Quotas applicables + invitation à vider la corbeille si saturé."""
    settings = request.app.state.settings
    used_self = db.scalar(
        select(func.coalesce(func.sum(Media.size_bytes), 0)).where(
            Media.user_id == user.id, Media.deleted_at.is_(None)
        )
    ) or 0
    personal = user.quota_bytes or settings.user_quota_bytes
    team_info = None
    remaining_checks = [personal - used_self]
    if user.team_id:
        team = db.get(Team, user.team_id)
        if team is not None:
            used_team = db.scalar(
                select(func.coalesce(func.sum(Media.size_bytes), 0)).where(
                    Media.team_id == team.id, Media.deleted_at.is_(None)
                )
            ) or 0
            team_info = {
                "id": team.id,
                "name": team.name,
                "quota_bytes": team.quota_bytes,
                "used_bytes": used_team,
            }
            if team.quota_bytes > 0:
                remaining_checks.append(team.quota_bytes - used_team)
    remaining = min(remaining_checks)
    warning = None
    if remaining <= 0:
        trashed = db.scalar(
            select(func.count()).select_from(Media).where(
                *_media_scope(db, user), Media.deleted_at.is_not(None)
            )
        ) or 0
        warning = (
            "Quota atteint. Videz la corbeille pour libérer de l'espace."
            if trashed
            else "Quota atteint. Supprimez d'anciens fichiers pour continuer."
        )
    return {
        "personal": {"quota_bytes": personal, "used_bytes": used_self},
        "team": team_info,
        "remaining_bytes": max(remaining, 0),
        "warning": warning,
    }



@router.get("/{media_id}")
def get_media(
    media_id: str,
    user: User = Depends(require_permission(Permission.MEDIA_VIEW)),
    db: Session = Depends(get_db),
) -> MediaOut:
    return MediaOut.model_validate(_get_media(db, user, media_id))


@router.get("/{media_id}/preview-file")
def media_preview_file(
    media_id: str,
    request: Request,
    user: User = Depends(require_permission(Permission.MEDIA_VIEW)),
    db: Session = Depends(get_db),
):
    """Fichier média pour le mur VNC / back-office (session cookie).

    PDF et Office (convertis en pages PNG) : la première page est servie
    comme image d'aperçu.
    """
    media = _get_media(db, user, media_id)
    storage = build_storage(request.app.state.settings)
    mime = media.mime_type
    if media.kind in (MediaKind.PDF, MediaKind.OFFICE) and media.pages_json:
        pages = json.loads(media.pages_json)
        if pages:
            return _serve_file(storage, pages[0], "image/png", 0, request)
    if media.kind == MediaKind.VIDEO and media.pages_json:
        # Vignette générée au traitement (frame ~3 s) : légère, immédiate.
        pages = json.loads(media.pages_json)
        if len(pages) > 1:
            return _serve_file(storage, pages[1], "image/jpeg", 0, request)
    return _serve_file(storage, media.storage_path, mime, media.size_bytes, request)


@router.get("/{media_id}/download")
def download_media(
    media_id: str,
    request: Request,
    user: User = Depends(require_permission(Permission.MEDIA_VIEW)),
    db: Session = Depends(get_db),
):
    """Télécharge le fichier original (session utilisateur, bibliothèque équipe)."""
    media = _get_media(db, user, media_id)
    storage = build_storage(request.app.state.settings)
    if not storage.exists(media.storage_path):
        raise HTTPException(status_code=404, detail="Fichier manquant")
    with storage.open_read(media.storage_path) as f:
        data = f.read()
    filename = re.sub(r"[^A-Za-z0-9._-]+", "_", media.original_filename or media.name)
    return Response(
        content=data,
        media_type=media.mime_type,
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "Content-Length": str(len(data)),
        },
    )


@router.get("/{media_id}/file")
def media_file(
    media_id: str,
    request: Request,
    db: Session = Depends(get_db),
    device: Device = Depends(get_device_from_request),
):
    media = db.get(Media, media_id)
    if media is None or media.org_id != device.org_id:
        raise HTTPException(status_code=404, detail="Média introuvable")
    storage = build_storage(request.app.state.settings)
    return _serve_file(storage, media.storage_path, media.mime_type, media.size_bytes, request)


@router.get("/{media_id}/device-file")
def media_device_file(
    media_id: str,
    request: Request,
    db: Session = Depends(get_db),
    device: Device = Depends(get_device_from_request),
):
    """Fichier média pour un Raspberry : téléchargement direct avec le token device.

    Permet de streamer un média (ex. commande « Afficher ») sans dépendre du
    manifeste publié. L'accès reste limité à l'organisation du device.
    PDF et Office : la première page (PNG) est servie.
    """
    media = db.get(Media, media_id)
    if media is None or media.org_id != device.org_id:
        raise HTTPException(status_code=404, detail="Média introuvable")
    storage = build_storage(request.app.state.settings)
    if media.kind in (MediaKind.PDF, MediaKind.OFFICE) and media.pages_json:
        pages = json.loads(media.pages_json)
        if pages:
            return _serve_file(storage, pages[0], "image/png", 0, request)
    return _serve_file(storage, media.storage_path, media.mime_type, media.size_bytes, request)


@router.get("/{media_id}/pages/{index}/device-file")
def media_page_device_file(
    media_id: str,
    index: int,
    request: Request,
    db: Session = Depends(get_db),
    device: Device = Depends(get_device_from_request),
):
    """Page PDF pour un Raspberry : téléchargement direct avec le token device."""
    media = db.get(Media, media_id)
    if media is None or media.org_id != device.org_id or not media.pages_json:
        raise HTTPException(status_code=404, detail="Média introuvable")
    pages = json.loads(media.pages_json)
    if index < 0 or index >= len(pages):
        raise HTTPException(status_code=404, detail="Page introuvable")
    storage = build_storage(request.app.state.settings)
    return _serve_file(storage, pages[index], "image/png", 0, request)


@router.get("/{media_id}/pages/{index}/preview-file")
def media_page_preview_file(
    media_id: str,
    index: int,
    request: Request,
    user: User = Depends(require_permission(Permission.MEDIA_VIEW)),
    db: Session = Depends(get_db),
):
    """Page PDF pour le back-office (session cookie)."""
    media = _get_media(db, user, media_id)
    if media.kind not in (MediaKind.PDF, MediaKind.OFFICE) or not media.pages_json:
        raise HTTPException(status_code=404, detail="Pas de pages PDF")
    pages = json.loads(media.pages_json)
    if index < 0 or index >= len(pages):
        raise HTTPException(status_code=404, detail="Page introuvable")
    storage = build_storage(request.app.state.settings)
    return _serve_file(storage, pages[index], "image/png", 0, request)


@router.get("/{media_id}/pages/{index}/file")
def media_page_file(
    media_id: str,
    index: int,
    request: Request,
    db: Session = Depends(get_db),
    device: Device = Depends(get_device_from_request),
):
    media = db.get(Media, media_id)
    if media is None or media.org_id != device.org_id or not media.pages_json:
        raise HTTPException(status_code=404, detail="Média introuvable")
    pages = json.loads(media.pages_json)
    if index < 0 or index >= len(pages):
        raise HTTPException(status_code=404, detail="Page introuvable")
    storage = build_storage(request.app.state.settings)
    return _serve_file(storage, pages[index], "image/png", 0, request)


def _serve_file(storage, rel_path: str, mime_type: str, size: int, request: Request):
    if not storage.exists(rel_path):
        raise HTTPException(status_code=404, detail="Fichier manquant")
    if size <= 0:
        size = storage.size(rel_path)
    range_header = request.headers.get("range")
    if range_header:
        match = re.match(r"bytes=(\d+)-(\d*)$", range_header.strip())
        if match:
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else size - 1
            if start >= size or end < start:
                return Response(
                    status_code=416, headers={"Content-Range": f"bytes */{size}"}
                )
            with storage.open_read(rel_path) as f:
                f.seek(start)
                data = f.read(end - start + 1)
            return Response(
                content=data,
                status_code=206,
                media_type=mime_type,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(len(data)),
                },
            )
    with storage.open_read(rel_path) as f:
        data = f.read()
    return Response(content=data, media_type=mime_type)


@router.delete("/{media_id}", status_code=204)
def delete_media(
    media_id: str,
    user: User = Depends(require_permission(Permission.MEDIA_DELETE)),
    db: Session = Depends(get_db),
) -> None:
    """Met le média à la corbeille (récupérable pendant 30 jours)."""
    media = _get_media(db, user, media_id)
    if media.deleted_at is None:
        media.deleted_at = dt.datetime.now(dt.UTC)
        db.commit()
        audit(db, "media.trash", "media", media_id, user=user)
        db.commit()


@router.post("/{media_id}/restore", status_code=200)
def restore_media(
    media_id: str,
    user: User = Depends(require_permission(Permission.MEDIA_DELETE)),
    db: Session = Depends(get_db),
) -> MediaOut:
    """Restaure un média depuis la corbeille."""
    media = _get_media(db, user, media_id)
    if media.deleted_at is None:
        raise HTTPException(status_code=409, detail="Média non supprimé")
    media.deleted_at = None
    db.commit()
    db.refresh(media)
    audit(db, "media.restore", "media", media_id, user=user)
    db.commit()
    return MediaOut.model_validate(media)


@router.delete("/{media_id}/permanent", status_code=204)
def purge_media(
    media_id: str,
    request: Request,
    user: User = Depends(require_permission(Permission.MEDIA_DELETE)),
    db: Session = Depends(get_db),
) -> None:
    """Supprime définitivement un média de la corbeille (fichiers inclus)."""
    media = _get_media(db, user, media_id)
    if media.deleted_at is None:
        raise HTTPException(status_code=409, detail="Média non dans la corbeille")
    storage = build_storage(request.app.state.settings)
    _purge_files(storage, media)
    db.delete(media)
    db.commit()
    audit(db, "media.purge", "media", media_id, user=user)
    db.commit()


@router.post("/trash/empty", status_code=200)
def empty_trash(
    request: Request,
    user: User = Depends(require_permission(Permission.MEDIA_DELETE)),
    db: Session = Depends(get_db),
) -> dict:
    """Vide la corbeille (ou celle de l'équipe) : purge définitive."""
    scope = *_media_scope(db, user),
    trashed = db.scalars(
        select(Media).where(*scope, Media.deleted_at.is_not(None))
    ).all()
    storage = build_storage(request.app.state.settings)
    for media in trashed:
        _purge_files(storage, media)
        db.delete(media)
    db.commit()
    audit(db, "media.trash_empty", "media", None, detail=f"{len(trashed)} média(s)", user=user)
    db.commit()
    return {"purged": len(trashed)}


def _purge_files(storage, media: Media) -> None:
    storage.delete(media.storage_path)
    if media.pages_json:
        try:
            for rel in json.loads(media.pages_json):
                storage.delete(rel)
        except (ValueError, TypeError):
            pass


@router.patch("/{media_id}")
def rename_media(
    media_id: str,
    body: MediaRename,
    user: User = Depends(require_permission(Permission.MEDIA_EDIT)),
    db: Session = Depends(get_db),
) -> MediaOut:
    """Renomme le titre d'affichage d'un média.

    L'extension ne fait pas partie du titre : si l'utilisateur la saisit,
    elle est retirée, puis l'extension réelle du fichier est réaffichée par
    le front. Le fichier original n'est jamais modifié.
    """
    media = _get_media(db, user, media_id)
    requested = body.name.strip()
    # Retire toute extension en fin de titre (ex. "video.mp4" → "video").
    requested = re.sub(r"\.[A-Za-z0-9]{1,8}$", "", requested).strip()
    if not requested:
        raise HTTPException(status_code=422, detail="Le titre ne peut pas être vide")
    media.name = requested
    db.commit()
    db.refresh(media)
    audit(db, "media.rename", "media", media_id, detail=body.name, user=user)
    db.commit()
    return MediaOut.model_validate(media)


