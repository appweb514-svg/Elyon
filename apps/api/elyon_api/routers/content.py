from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from elyon_api.db import get_db
from elyon_api.deps import (
    audit,
    require_permission,
    require_same_org,
    require_site_access,
)
from elyon_api.models import (
    Device,
    Event,
    EventLevel,
    Media,
    Playlist,
    PlaylistItem,
    PlaylistRevision,
    Role,
    Schedule,
    ScheduleExclusion,
    Site,
    User,
)
from elyon_api.permissions import Permission
from elyon_api.schemas import (
    PlaylistCreate,
    PlaylistDetailOut,
    PlaylistDiffOut,
    PlaylistDuplicateIn,
    PlaylistItemIn,
    PlaylistItemOut,
    PlaylistOut,
    PlaylistRevisionOut,
    PlaylistValidationOut,
    ScheduleCreate,
    ScheduleExclusionIn,
    ScheduleOut,
    SchedulePatch,
)
from elyon_api.services.playlist_revision import (
    PlaylistValidationError,
    create_revision,
    diff_playlist,
    draft_items,
    published_revision,
    revision_items,
    validate_playlist,
)
from elyon_api.services.schedule import find_overlaps

router = APIRouter(prefix="/api", tags=["content"])


def _playlist_visible(user: User, playlist: Playlist) -> bool:
    """Périmètre de visibilité d'une playliste.

    - Admins (superadmin / org admin) : tout leur org ;
    - Autres : les playlistes globales (team_id NULL — créées par un
      administrateur ou historiques) + celles de leur propre équipe.
    """
    if user.role in (Role.SUPERADMIN, Role.ORG_ADMIN):
        return True
    return playlist.team_id is None or playlist.team_id == user.team_id


@router.get("/playlists")
def list_playlists(
    user: User = Depends(require_permission(Permission.PLAYLIST_VIEW)),  # noqa: E501
    db: Session = Depends(get_db),
) -> list[PlaylistOut]:
    stmt = select(Playlist).order_by(Playlist.name)
    if user.role != Role.SUPERADMIN:
        stmt = stmt.where(Playlist.org_id == user.org_id)
        if user.role != Role.ORG_ADMIN:
            stmt = stmt.where(
                (Playlist.team_id.is_(None)) | (Playlist.team_id == user.team_id)
            )
    return [PlaylistOut.model_validate(p) for p in db.scalars(stmt)]


def _playlist_detail(playlist: Playlist, db: Session) -> PlaylistDetailOut:
    out = PlaylistDetailOut.model_validate(playlist)
    out.items = [PlaylistItemOut.model_validate(item) for item in draft_items(playlist)]
    revision = published_revision(db, playlist)
    out.published_version = revision.version if revision else None
    out.draft_changed = diff_playlist(db, playlist)["changed"]
    return out


def _get_playlist(db: Session, user: User, playlist_id: str) -> Playlist:
    playlist = db.get(Playlist, playlist_id)
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist introuvable")
    require_same_org(db, user, playlist.org_id)
    if not _playlist_visible(user, playlist):
        # 404 (pas 403) : ne pas révéler l'existence d'une playliste étrangère.
        raise HTTPException(status_code=404, detail="Playlist introuvable")
    return playlist


def _require_playlist_edit(db: Session, user: User, playlist: Playlist) -> None:
    """Vérifie que l'utilisateur peut MODIFIER la playliste.

    Au-delà de la visibilité : une playliste d'équipe n'est éditable que par
    ses membres (ou les admins). Les playlistes globales restent éditables par
    quiconque a la permission PLAYLIST_EDIT dans l'org (comportement historique).
    """
    require_same_org(db, user, playlist.org_id)
    if not _playlist_visible(user, playlist):
        raise HTTPException(status_code=404, detail="Playlist introuvable")
    if user.role not in (Role.SUPERADMIN, Role.ORG_ADMIN):
        if playlist.team_id is not None and playlist.team_id != user.team_id:
            raise HTTPException(status_code=403, detail="Playlist réservée à votre équipe")


@router.post("/playlists", status_code=201)
def create_playlist(
    body: PlaylistCreate,
    user: User = Depends(require_permission(Permission.PLAYLIST_CREATE)),  # noqa: E501
    db: Session = Depends(get_db),
) -> PlaylistOut:
    if user.role == Role.SUPERADMIN:
        raise HTTPException(status_code=400, detail="org_id requis pour un superadmin")
    if db.scalar(
        select(Playlist).where(Playlist.org_id == user.org_id, Playlist.name == body.name)
    ):
        raise HTTPException(status_code=409, detail="Playlist déjà existante")
    # Les admins créent des playlistes globales (visibles par tout l'org) ;
    # les autres rattachent la playliste à leur équipe.
    team_id = None if user.role in (Role.SUPERADMIN, Role.ORG_ADMIN) else user.team_id
    playlist = Playlist(
        org_id=user.org_id, team_id=team_id, name=body.name, description=body.description
    )
    db.add(playlist)
    db.commit()
    db.refresh(playlist)
    audit(db, "playlist.create", "playlist", playlist.id, user=user)
    db.commit()
    return PlaylistOut.model_validate(playlist)


@router.get("/playlists/{playlist_id}")
def get_playlist(
    playlist_id: str,
    user: User = Depends(require_permission(Permission.PLAYLIST_VIEW)),  # noqa: E501
    db: Session = Depends(get_db)
) -> PlaylistDetailOut:
    playlist = _get_playlist(db, user, playlist_id)
    return _playlist_detail(playlist, db)


@router.get("/playlists/{playlist_id}/validate")
def validate_playlist_route(
    playlist_id: str,
    user: User = Depends(require_permission(Permission.PLAYLIST_VIEW)),
    db: Session = Depends(get_db),
) -> PlaylistValidationOut:
    playlist = _get_playlist(db, user, playlist_id)
    return PlaylistValidationOut.model_validate(validate_playlist(db, playlist))


@router.get("/playlists/{playlist_id}/diff")
def playlist_diff(
    playlist_id: str,
    user: User = Depends(require_permission(Permission.PLAYLIST_VIEW)),
    db: Session = Depends(get_db),
) -> PlaylistDiffOut:
    result = diff_playlist(db, _get_playlist(db, user, playlist_id))
    return PlaylistDiffOut.model_validate(result)


@router.get("/playlists/{playlist_id}/revisions")
def list_playlist_revisions(
    playlist_id: str,
    user: User = Depends(require_permission(Permission.PLAYLIST_VIEW)),
    db: Session = Depends(get_db),
) -> list[PlaylistRevisionOut]:
    playlist = _get_playlist(db, user, playlist_id)
    revisions = db.scalars(
        select(PlaylistRevision)
        .where(PlaylistRevision.playlist_id == playlist.id)
        .order_by(PlaylistRevision.version.desc())
    )
    return [
        PlaylistRevisionOut(
            id=revision.id,
            playlist_id=revision.playlist_id,
            version=revision.version,
            status=revision.status,
            items=[PlaylistItemOut.model_validate(item) for item in revision_items(revision)],
            created_by=revision.created_by,
            created_at=revision.created_at,
        )
        for revision in revisions
    ]


@router.post("/playlists/{playlist_id}/duplicate", status_code=201)
def duplicate_playlist(
    playlist_id: str,
    body: PlaylistDuplicateIn,
    user: User = Depends(require_permission(Permission.PLAYLIST_CREATE)),
    db: Session = Depends(get_db),
) -> PlaylistDetailOut:
    source = _get_playlist(db, user, playlist_id)
    duplicate = db.scalar(
        select(Playlist).where(Playlist.org_id == source.org_id, Playlist.name == body.name)
    )
    if duplicate is not None:
        raise HTTPException(status_code=409, detail="Playlist déjà existante")
    copy = Playlist(
        org_id=source.org_id,
        team_id=source.team_id,
        name=body.name,
        description=body.description if body.description is not None else source.description,
    )
    db.add(copy)
    db.flush()
    for item in draft_items(source):
        db.add(
            PlaylistItem(
                playlist_id=copy.id,
                media_id=item.media_id,
                position=item.position,
                duration_seconds=item.duration_seconds,
            )
        )
    db.commit()
    db.refresh(copy)
    audit(db, "playlist.duplicate", "playlist", copy.id, detail=source.id, user=user)
    db.commit()
    return _playlist_detail(copy, db)


@router.delete("/playlists/{playlist_id}", status_code=204)
def delete_playlist(
    playlist_id: str,
    request: Request,
    user: User = Depends(require_permission(Permission.PLAYLIST_DELETE)),  # noqa: E501
    db: Session = Depends(get_db)
) -> None:
    """Supprime la playlist ET tous ses plannings (dès que la playlist est
    retirée, ses plannings disparaissent automatiquement des écrans)."""
    playlist = _get_playlist(db, user, playlist_id)
    _require_playlist_edit(db, user, playlist)
    affected_sites: set[str] = set()
    schedules = db.scalars(
        select(Schedule).where(Schedule.playlist_id == playlist.id)
    ).all()
    for schedule in schedules:
        affected_sites.add(schedule.site_id)
        db.delete(schedule)
    db.delete(playlist)
    db.commit()
    # Re-publication : les écrans concernés perdent ce contenu immédiatement.
    for site_id in affected_sites:
        _republish_site_devices(db, site_id, request.app.state.settings)
    audit(db, "playlist.delete", "playlist", playlist_id, user=user)
    db.commit()


@router.post("/playlists/{playlist_id}/publish")
def publish_playlist(
    playlist_id: str,
    request: Request,
    user: User = Depends(require_permission(Permission.PLAYLIST_PUBLISH)),
    db: Session = Depends(get_db),
) -> PlaylistRevisionOut:
    playlist = _get_playlist(db, user, playlist_id)
    _require_playlist_edit(db, user, playlist)
    current_diff = diff_playlist(db, playlist)
    if not current_diff["changed"]:
        revision = published_revision(db, playlist)
        if revision is not None:
            return PlaylistRevisionOut(
                id=revision.id,
                playlist_id=revision.playlist_id,
                version=revision.version,
                status=revision.status,
                items=[PlaylistItemOut.model_validate(item) for item in revision_items(revision)],
                created_by=revision.created_by,
                created_at=revision.created_at,
            )
    try:
        revision = create_revision(db, playlist, user_id=user.id)
    except PlaylistValidationError as exc:
        raise HTTPException(status_code=422, detail={"errors": exc.errors}) from exc
    db.commit()
    _republish_affected_devices(db, playlist.id, request.app.state.settings)
    audit(db, "playlist.publish", "playlist", playlist.id, detail=f"v{revision.version}", user=user)
    db.commit()
    return PlaylistRevisionOut(
        id=revision.id,
        playlist_id=revision.playlist_id,
        version=revision.version,
        status=revision.status,
        items=[PlaylistItemOut.model_validate(item) for item in json.loads(revision.items_json)],
        created_by=revision.created_by,
        created_at=revision.created_at,
    )


@router.post("/playlists/{playlist_id}/items", status_code=201)
def add_item(
    playlist_id: str,
    body: PlaylistItemIn,
    user: User = Depends(require_permission(Permission.PLAYLIST_EDIT)),  # noqa: E501
    db: Session = Depends(get_db),
) -> PlaylistDetailOut:
    playlist = _get_playlist(db, user, playlist_id)
    _require_playlist_edit(db, user, playlist)
    media = db.get(Media, body.media_id)
    if media is None or media.org_id != playlist.org_id:
        raise HTTPException(status_code=400, detail="Média invalide")
    next_pos = db.scalar(
        select(func.max(PlaylistItem.position)).where(PlaylistItem.playlist_id == playlist.id)
    ) or 0
    item = PlaylistItem(
        playlist_id=playlist.id,
        media_id=media.id,
        position=next_pos + 1,
        duration_seconds=body.duration_seconds,
    )
    db.add(item)
    db.commit()
    db.refresh(playlist)
    audit(db, "playlist.add_item", "playlist", playlist.id, detail=media.id, user=user)
    db.commit()
    return _playlist_detail(playlist, db)


@router.delete("/playlists/{playlist_id}/items/{item_id}", status_code=204)
def remove_item(
    playlist_id: str,
    item_id: str,
    user: User = Depends(require_permission(Permission.PLAYLIST_EDIT)),
    db: Session = Depends(get_db),
) -> None:
    playlist = _get_playlist(db, user, playlist_id)
    _require_playlist_edit(db, user, playlist)
    item = db.get(PlaylistItem, item_id)
    if item is None or item.playlist_id != playlist.id:
        raise HTTPException(status_code=404, detail="Élément introuvable")
    db.delete(item)
    db.commit()
    audit(db, "playlist.remove_item", "playlist", playlist.id, detail=item_id, user=user)
    db.commit()


@router.post("/sites/{site_id}/schedules/reorder")
def reorder_schedules(
    site_id: str,
    schedule_ids: list[str],
    request: Request,
    user: User = Depends(require_permission(Permission.SCHEDULE_EDIT)),  # noqa: E501
    db: Session = Depends(get_db),
) -> list[ScheduleOut]:
    """Ordre de priorité des contenus affichés sur les écrans d'un site.

    L'ordre donné réattribue des priorités décroissantes (premier = priorité
    la plus haute). La priorité départage les plannings simultanés : le
    contenu du haut de liste gagne.
    """
    site = _get_site(db, user, site_id)
    schedules = db.scalars(
        select(Schedule).where(Schedule.site_id == site.id)
    ).all()
    by_id = {s.id: s for s in schedules}
    if set(schedule_ids) != set(by_id):
        raise HTTPException(status_code=400, detail="Liste de plannings incomplète")
    total = len(schedule_ids)
    for index, schedule_id in enumerate(schedule_ids):
        by_id[schedule_id].priority = total - index
    db.commit()
    # Re-publication immédiate des écrans du site : le nouvel ordre prend
    # effet sans action manuelle.
    from elyon_api.models import Device
    from elyon_api.services.manifest import publish_manifest

    devices = db.scalars(
        select(Device).where(Device.site_id == site.id, Device.is_preview.is_(False))
    ).all()
    for device in devices:
        try:
            publish_manifest(db, device, request.app.state.settings)
        except Exception:  # noqa: BLE001
            continue
    stmt = (
        select(Schedule)
        .where(Schedule.site_id == site.id)
        .order_by(Schedule.priority.desc())
    )
    return [ScheduleOut.model_validate(s) for s in db.scalars(stmt)]


@router.post("/playlists/{playlist_id}/reorder")
def reorder_items(
    playlist_id: str,
    item_ids: list[str],
    user: User = Depends(require_permission(Permission.PLAYLIST_EDIT)),  # noqa: E501
    db: Session = Depends(get_db),
) -> PlaylistDetailOut:
    playlist = _get_playlist(db, user, playlist_id)
    _require_playlist_edit(db, user, playlist)
    existing = {item.id: item for item in playlist.items}
    if set(item_ids) != set(existing):
        raise HTTPException(status_code=400, detail="Liste d'éléments incomplète")
    for position, item_id in enumerate(item_ids, start=1):
        existing[item_id].position = position
    db.commit()
    db.refresh(playlist)
    return _playlist_detail(playlist, db)


def _get_site(db: Session, user: User, site_id: str) -> Site:
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site introuvable")
    require_site_access(db, user, site.org_id)
    return site


def _republish_affected_devices(db: Session, playlist_id: str, settings) -> int:
    """Republie les devices dont le manifeste dépend de cette playlist.

    Garantit qu'un contenu retiré d'une playlist (item retiré, planning
    désactivé) quitte bien les écrans au prochain cycle agent — sans
    publication manuelle. Les devices d'aperçu restent en live brouillon.
    """
    from elyon_api.models import Device
    from elyon_api.services.manifest import publish_manifest

    devices = db.scalars(
        select(Device).join(Schedule, Schedule.site_id == Device.site_id).where(
            Schedule.playlist_id == playlist_id,
            Schedule.is_active.is_(True),
            Device.is_preview.is_(False),
        ).distinct()
    ).all()
    count = 0
    for device in devices:
        try:
            publish_manifest(db, device, settings)
            count += 1
        except Exception:  # noqa: BLE001 — une publication en échec n'arrête pas les autres
            continue
    return count


@router.get("/schedules")
def list_schedules(
    site_id: str | None = None,
    device_id: str | None = None,
    user: User = Depends(require_permission(Permission.SCHEDULE_VIEW)),  # noqa: E501
    db: Session = Depends(get_db),
) -> list[ScheduleOut]:
    stmt = select(Schedule).order_by(Schedule.start_at.desc())
    if user.role != Role.SUPERADMIN:
        stmt = stmt.where(Schedule.org_id == user.org_id)
    if site_id:
        stmt = stmt.where(Schedule.site_id == site_id)
    outs = [ScheduleOut.model_validate(s) for s in db.scalars(stmt)]
    if device_id:
        excluded = set(
            db.scalars(
                select(ScheduleExclusion.schedule_id).where(
                    ScheduleExclusion.device_id == device_id
                )
            )
        )
        for out in outs:
            out.excluded_for_this_device = out.id in excluded
    return outs


def _get_schedule_exclusion_context(
    db: Session, user: User, schedule_id: str, device_id: str
) -> tuple[Schedule, Device]:
    schedule = db.get(Schedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Planning introuvable")
    require_site_access(db, user, schedule.org_id)
    device = db.get(Device, device_id)
    if device is None or device.site_id != schedule.site_id:
        raise HTTPException(status_code=400, detail="Device invalide pour ce planning")
    return schedule, device


@router.post("/schedules/{schedule_id}/exclusions", status_code=201)
def exclude_schedule_from_device(
    schedule_id: str,
    body: ScheduleExclusionIn,
    request: Request,
    user: User = Depends(require_permission(Permission.SCHEDULE_EDIT)),  # noqa: E501
    db: Session = Depends(get_db),
) -> dict:
    """Masque un planning sur UN écran précis (sans l'affecter aux autres).

    Typique : un planning partagé « tous les écrans du site » désactivé depuis
    la page d'un device — seul le manifeste de cet écran change.
    """
    schedule, device = _get_schedule_exclusion_context(db, user, schedule_id, body.device_id)
    existing = db.scalar(
        select(ScheduleExclusion).where(
            ScheduleExclusion.schedule_id == schedule.id,
            ScheduleExclusion.device_id == device.id,
        )
    )
    if existing is None:
        db.add(ScheduleExclusion(schedule_id=schedule.id, device_id=device.id))
        db.commit()
    from elyon_api.services.manifest import publish_manifest

    publish_manifest(db, device, request.app.state.settings)
    audit(db, "schedule.exclude", "schedule", schedule.id, detail=device.id, user=user)
    db.commit()
    return {"ok": True}


@router.delete("/schedules/{schedule_id}/exclusions/{device_id}", status_code=204)
def include_schedule_on_device(
    schedule_id: str,
    device_id: str,
    request: Request,
    user: User = Depends(require_permission(Permission.SCHEDULE_EDIT)),  # noqa: E501
    db: Session = Depends(get_db),
) -> None:
    """Réaffiche un planning sur un écran (retire l'exclusion locale)."""
    schedule, device = _get_schedule_exclusion_context(db, user, schedule_id, device_id)
    row = db.scalar(
        select(ScheduleExclusion).where(
            ScheduleExclusion.schedule_id == schedule.id,
            ScheduleExclusion.device_id == device.id,
        )
    )
    if row is not None:
        db.delete(row)
        db.commit()
    from elyon_api.services.manifest import publish_manifest

    publish_manifest(db, device, request.app.state.settings)
    audit(db, "schedule.include", "schedule", schedule.id, detail=device.id, user=user)
    db.commit()


@router.post("/schedules", status_code=201)
def create_schedule(
    body: ScheduleCreate,
    user: User = Depends(require_permission(Permission.SCHEDULE_CREATE)),  # noqa: E501
    db: Session = Depends(get_db),
) -> ScheduleOut:
    if body.end_at <= body.start_at:
        raise HTTPException(status_code=422, detail="end_at doit suivre start_at")
    site = _get_site(db, user, body.site_id)
    playlist = db.get(Playlist, body.playlist_id)
    if (
        playlist is None
        or playlist.org_id != site.org_id
        or not _playlist_visible(user, playlist)
    ):
        raise HTTPException(status_code=400, detail="Playlist invalide")
    overlaps = find_overlaps(db, site.id, body.start_at, body.end_at)
    if overlaps:
        names = ", ".join(o.name for o in overlaps)
        db.add(
            Event(
                org_id=site.org_id,
                site_id=site.id,
                type="schedule_conflict",
                level=EventLevel.WARNING,
                message=f"Conflit de planning avec : {names}",
            )
        )
        db.commit()
    # Cible optionnelle : un seul écran (device du site) ou tous les écrans.
    target_device_id: str | None = None
    if getattr(body, "device_id", None):
        device = db.get(Device, body.device_id)
        if device is None or device.site_id != site.id:
            raise HTTPException(status_code=400, detail="Écran invalide pour ce site")
        target_device_id = device.id
    schedule = Schedule(
        org_id=site.org_id,
        site_id=site.id,
        playlist_id=playlist.id,
        name=body.name,
        start_at=body.start_at,
        end_at=body.end_at,
        priority=body.priority,
        is_active=body.is_active,
        device_id=target_device_id,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    audit(
        db, "schedule.create", "schedule", schedule.id,
        detail=f"priority={body.priority}", user=user,
    )
    db.commit()
    return ScheduleOut.model_validate(schedule)


def _get_schedule(db: Session, user: User, schedule_id: str) -> Schedule:
    schedule = db.get(Schedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Planning introuvable")
    require_site_access(db, user, schedule.org_id)
    return schedule


def _republish_site_devices(db: Session, site_id: str, settings) -> None:
    """Republie les écrans d'un site (contenu modifié/désactivé/supprimé)."""
    from elyon_api.models import Device
    from elyon_api.services.manifest import publish_manifest

    devices = db.scalars(
        select(Device).where(Device.site_id == site_id, Device.is_preview.is_(False))
    ).all()
    for device in devices:
        try:
            publish_manifest(db, device, settings)
        except Exception:  # noqa: BLE001 — une publication en échec n'arrête pas les autres
            continue


@router.patch("/schedules/{schedule_id}")
def patch_schedule(
    schedule_id: str,
    request: Request,
    body: SchedulePatch,
    user: User = Depends(require_permission(Permission.SCHEDULE_EDIT)),  # noqa: E501
    db: Session = Depends(get_db),
) -> ScheduleOut:
    schedule = _get_schedule(db, user, schedule_id)
    data = body.model_dump(exclude_none=True)
    if "playlist_id" in data:
        playlist = db.get(Playlist, data["playlist_id"])
        if (
            playlist is None
            or playlist.org_id != schedule.org_id
            or not _playlist_visible(user, playlist)
        ):
            raise HTTPException(status_code=400, detail="Playlist invalide")
    start = data.get("start_at", schedule.start_at)
    end = data.get("end_at", schedule.end_at)
    if end <= start:
        raise HTTPException(status_code=422, detail="end_at doit suivre start_at")
    for key, value in data.items():
        setattr(schedule, key, value)
    db.commit()
    db.refresh(schedule)
    _republish_site_devices(db, schedule.site_id, request.app.state.settings)
    audit(db, "schedule.update", "schedule", schedule.id, user=user)
    db.commit()
    return ScheduleOut.model_validate(schedule)


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(
    schedule_id: str,
    request: Request,
    user: User = Depends(require_permission(Permission.SCHEDULE_DELETE)),  # noqa: E501
    db: Session = Depends(get_db)
) -> None:
    schedule = _get_schedule(db, user, schedule_id)
    site_id = schedule.site_id
    db.delete(schedule)
    db.commit()
    _republish_site_devices(db, site_id, request.app.state.settings)
    audit(db, "schedule.delete", "schedule", schedule_id, user=user)
    db.commit()