from __future__ import annotations

import datetime as dt
import html as html_mod
import json
import time
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from elyon_api.db import get_db
from elyon_api.deps import (
    audit,
    get_device_from_request,
    require_permission,
    require_roles,
    require_site_access,
)
from elyon_api.services import playback_state, widget_feed
from elyon_api.models import (
    AuditLog,
    Command,
    CommandStatus,
    CommandType,
    Device,
    DeviceStatus,
    Event,
    EventLevel,
    Manifest,
    Media,
    MediaKind,
    MediaStatus,
    Role,
    User,
    ensure_utc,
)
from elyon_api.permissions import Permission
from elyon_api.schemas import (
    AuditLogOut,
    CommandAck,
    CommandIn,
    CommandOut,
    EventOut,
    HeartbeatIn,
)
from elyon_api.services.storage import build_storage

router = APIRouter(prefix="/api", tags=["ops"])

admin = require_roles(
    Role.SUPERADMIN, Role.ORG_ADMIN, Role.SITE_MANAGER, Role.OPERATOR, Role.VIEWER
)


def _add_event(db: Session, org_id: str, site_id: str | None, device_id: str | None,
               type_: str, level: EventLevel, message: str, detail: str | None = None) -> None:
    db.add(Event(org_id=org_id, site_id=site_id, device_id=device_id, type=type_,
                 level=level, message=message, detail=detail))


@router.get("/events")
def list_events(
    site_id: str | None = None,
    device_id: str | None = None,
    level: EventLevel | None = None,
    limit: int = 100,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
) -> list[EventOut]:
    stmt = select(Event).order_by(Event.created_at.desc()).limit(min(limit, 500))
    if user.role != Role.SUPERADMIN:
        stmt = stmt.where(Event.org_id == user.org_id)
    if site_id:
        stmt = stmt.where(Event.site_id == site_id)
    if device_id:
        stmt = stmt.where(Event.device_id == device_id)
    if level:
        stmt = stmt.where(Event.level == level)
    return [EventOut.model_validate(e) for e in db.scalars(stmt)]


@router.post("/devices/{device_id}/heartbeat")
def heartbeat(
    device_id: str,
    body: HeartbeatIn,
    request: Request,
    device: Device = Depends(get_device_from_request),
    db: Session = Depends(get_db),
) -> dict:
    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Accès refusé")
    now = dt.datetime.now(dt.UTC)
    settings = request.app.state.settings
    last = ensure_utc(device.last_seen_at) if device.last_seen_at else None
    was_offline = last is None or (now - last).total_seconds() > settings.offline_grace_seconds
    first_seen = device.last_seen_at is None
    device.last_seen_at = now
    device.player_state = body.state
    device.current_media_id = body.current_media_id
    # Télémétrie
    device.uptime_seconds = body.uptime_seconds
    device.load_avg = body.load_avg
    device.memory_percent = body.memory_percent
    device.cpu_percent = body.cpu_percent
    device.storage_free_bytes = body.storage_free_bytes
    device.lan_ip = body.lan_ip
    device.wifi_ssid = body.wifi_ssid
    db.commit()
    _queue_advance_if_needed(db, device)
    db.commit()
    if first_seen:
        _add_event(db, device.org_id, device.site_id, device.id, "device_online",
                   EventLevel.INFO, f"Appareil {device.name} connecté")
    elif was_offline:
        _add_event(db, device.org_id, device.site_id, device.id, "device_online",
                   EventLevel.INFO, f"Appareil {device.name} de retour")
    # Proof-of-play : journaliser tout changement de média ou d'état
    _record_playback(db, device, body)
    db.commit()
    interval = 5 if device.is_preview else settings.heartbeat_interval_seconds
    return {
        "status": "ok",
        "server_time": now.isoformat(),
        "heartbeat_interval_seconds": interval,
    }


def _record_playback(db: Session, device: Device, body: HeartbeatIn) -> None:
    """Insère un événement de lecture si l'état ou le média a changé.

    Chaque heartbeat avec `state=playing` et un `current_media_id` différent
    déclenche un enregistrement dans `playback_events` — base du proof-of-play.
    """
    from elyon_api.models import PlaybackEvent as _PE

    if device.current_media_id is None and body.state != "idle":
        return
    if body.state == "idle":
        if device.current_media_id is not None:
            last = db.scalar(
                select(_PE)
                .where(_PE.device_id == device.id)
                .order_by(_PE.recorded_at.desc())
                .limit(1)
            )
            if last is not None and last.state == "playing":
                db.add(
                    _PE(
                        org_id=device.org_id,
                        device_id=device.id,
                        media_id=device.current_media_id,
                        state="end",
                        recorded_at=dt.datetime.now(dt.UTC),
                    )
                )
        return
    if body.state == "playing" and device.current_media_id is not None:
        db.add(
            _PE(
                org_id=device.org_id,
                device_id=device.id,
                media_id=device.current_media_id,
                state="playing",
                recorded_at=dt.datetime.now(dt.UTC),
            )
        )


@router.get("/devices/{device_id}/commands")
def fetch_commands(
    device_id: str,
    device: Device = Depends(get_device_from_request),
    db: Session = Depends(get_db),
) -> list[CommandOut]:
    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Accès refusé")
    now = dt.datetime.now(dt.UTC)
    commands = db.scalars(
        select(Command)
        .where(
            Command.device_id == device_id,
            Command.status.in_([CommandStatus.PENDING, CommandStatus.DELIVERED]),
        )
        .order_by(Command.created_at)
    ).all()
    for cmd in commands:
        cmd.status = CommandStatus.DELIVERED
        cmd.delivered_at = now
    db.commit()
    return [CommandOut.model_validate(c) for c in commands]


def _device_queue_items(device: Device) -> list[dict[str, str]]:
    if not device.queue_json:
        return []
    try:
        items = json.loads(device.queue_json)
    except (ValueError, TypeError):
        return []
    return [i for i in items if isinstance(i, dict) and i.get("media_id")]


def _issue_show(db: Session, device: Device, media: Media, user: User) -> Command:
    for stale in db.scalars(
        select(Command).where(
            Command.device_id == device.id,
            Command.type == CommandType.SHOW,
            Command.status == CommandStatus.PENDING,
        )
    ):
        stale.status = CommandStatus.FAILED
        stale.error = "Remplacé par une diffusion plus récente"
    cmd = Command(
        device_id=device.id,
        type=CommandType.SHOW,
        payload=json.dumps(
            {"media_id": media.id, "name": media.name, "kind": media.kind.value}
        ),
    )
    db.add(cmd)
    device.current_media_id = media.id
    device.player_state = "playing"
    audit(db, "media.show", "media", media.id, detail=f"device={device.id} {media.name}", user=user)
    db.commit()
    db.refresh(cmd)
    return cmd


@router.get("/devices/{device_id}/widgets-feed")
def device_widgets_feed(
    device_id: str,
    device: Device = Depends(get_device_from_request),
    db: Session = Depends(get_db),
) -> dict:
    """Données de widgets résolues pour le player web (auth device).

    Retourne les textes prêts à l'affichage : ticker (RSS résolu ou texte
    déroulant), météo du bandeau. Cache serveur 5 min par widget.
    """
    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Device mismatch")
    out: dict[str, Any] = {"ticker_text": None, "ticker_speed": None, "weather_text": None}
    screen = device.screen
    widgets: list[dict[str, Any]] = []
    if screen is not None and screen.widgets_json:
        try:
            loaded = json.loads(screen.widgets_json)
            if isinstance(loaded, list):
                widgets = [w for w in loaded if isinstance(w, dict) and w.get("visible", True)]
        except (ValueError, TypeError):
            widgets = []
    for widget in widgets:
        kind = str(widget.get("type") or "")
        position = str(widget.get("position") or "")
        params = widget.get("params") or {}
        if position == "bottom-ticker" and kind in ("ticker", "text", "rss") and not out["ticker_text"]:
            if kind in ("ticker", "text"):
                out["ticker_text"] = str(params.get("text") or "") or None
                out["ticker_speed"] = str(params.get("speed") or "normal")
            elif kind == "rss":
                entry = _widget_feed_entry("rss", params) or {}
                items = [str(i) for i in (entry.get("items") or []) if str(i).strip()]
                if items:
                    out["ticker_text"] = "  •  ".join(items[:5])
        elif position == "top-band" and kind == "weather" and not out["weather_text"]:
            city = str(params.get("city") or "").strip() or "Météo"
            entry = _widget_feed_entry("weather", params) or {}
            temp = entry.get("temperature")
            out["weather_text"] = f"{city} · {temp:.0f}°C" if isinstance(temp, (int, float)) else city
    return out


@router.get("/devices/{device_id}/queue")
def get_device_queue(
    device_id: str,
    user: User = Depends(require_permission(Permission.DEVICE_VIEW)),
    db: Session = Depends(get_db),
) -> dict:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Appareil introuvable")
    require_site_access(db, user, device.org_id)
    items = []
    for item in _device_queue_items(device):
        media = db.get(Media, item["media_id"])
        if media is None:
            continue
        items.append(
            {
                "media_id": media.id,
                "name": media.name,
                "kind": media.kind.value,
                "playing": device.current_media_id == media.id
                and device.player_state == "playing",
            }
        )
    return {
        "items": items,
        "state": device.player_state,
        "current_media_id": device.current_media_id,
    }


@router.post("/devices/{device_id}/queue", status_code=201)
def queue_add(
    device_id: str,
    body: dict,
    user: User = Depends(require_permission(Permission.DEVICE_COMMAND)),
    db: Session = Depends(get_db),
) -> dict:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Appareil introuvable")
    require_site_access(db, user, device.org_id)
    media = db.get(Media, str(body.get("media_id") or ""))
    if media is None:
        raise HTTPException(status_code=404, detail="Média introuvable")
    if media.org_id != device.org_id:
        raise HTTPException(status_code=400, detail="Média hors organisation de l'appareil")
    items = _device_queue_items(device)
    if any(i["media_id"] == media.id for i in items):
        raise HTTPException(status_code=409, detail="Déjà dans la file")
    items.append({"media_id": media.id})
    device.queue_json = json.dumps(items)
    audit(db, "device.queue_add", "device", device.id, detail=media.name, user=user)
    db.commit()
    return {"items": items}


@router.delete("/devices/{device_id}/queue/{media_id}", status_code=204)
def queue_remove(
    device_id: str,
    media_id: str,
    user: User = Depends(require_permission(Permission.DEVICE_COMMAND)),
    db: Session = Depends(get_db),
) -> None:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Appareil introuvable")
    require_site_access(db, user, device.org_id)
    items = [i for i in _device_queue_items(device) if i["media_id"] != media_id]
    device.queue_json = json.dumps(items)
    if device.current_media_id == media_id:
        # Le média retiré était en lecture : STOP_SHOW pour ne pas le relancer.
        cmd = Command(
            device_id=device.id,
            type=CommandType.STOP_SHOW,
            payload=json.dumps({"media_id": media_id}),
        )
        db.add(cmd)
        device.current_media_id = None
        device.player_state = "idle"
        playback_state.mark_queue_stopped(device.id)
        audit(db, "device.queue_remove_playing", "device", device.id, detail=media_id, user=user)
    else:
        audit(db, "device.queue_remove", "device", device.id, detail=media_id, user=user)
    db.commit()


@router.post("/devices/{device_id}/queue/play", status_code=201)
def queue_play(
    device_id: str,
    body: dict,
    user: User = Depends(require_permission(Permission.DEVICE_COMMAND)),
    db: Session = Depends(get_db),
) -> dict:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Appareil introuvable")
    require_site_access(db, user, device.org_id)
    if device.status != DeviceStatus.APPROVED:
        raise HTTPException(status_code=409, detail="Appareil indisponible")
    items = _device_queue_items(device)
    if not items:
        raise HTTPException(status_code=400, detail="File vide")
    media_id = str(body.get("media_id") or "") or items[0]["media_id"]
    if not any(i["media_id"] == media_id for i in items):
        raise HTTPException(status_code=404, detail="Média hors file")
    media = db.get(Media, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Média introuvable")
    # Le média lu passe en tête de file.
    items = [i for i in items if i["media_id"] != media_id]
    items.insert(0, {"media_id": media_id})
    device.queue_json = json.dumps(items)
    cmd = _issue_show(db, device, media, user)
    return {"command_id": cmd.id, "media_id": media.id}


@router.post("/devices/{device_id}/queue/next", status_code=201)
def queue_next(
    device_id: str,
    user: User = Depends(require_permission(Permission.DEVICE_COMMAND)),
    db: Session = Depends(get_db),
) -> dict:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Appareil introuvable")
    require_site_access(db, user, device.org_id)
    if device.status != DeviceStatus.APPROVED:
        raise HTTPException(status_code=409, detail="Appareil indisponible")
    items = _device_queue_items(device)
    if len(items) < 2:
        raise HTTPException(status_code=400, detail="Aucun média suivant")
    next_id = items[1]["media_id"]
    media = db.get(Media, next_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Média introuvable")
    items = items[1:] + [items[0]]  # rotation : le média lu passe en fin de file
    device.queue_json = json.dumps(items)
    cmd = _issue_show(db, device, media, user)
    return {"command_id": cmd.id, "media_id": next_id}


@router.post("/devices/{device_id}/queue/stop", status_code=201)
def queue_stop(
    device_id: str,
    user: User = Depends(require_permission(Permission.DEVICE_COMMAND)),
    db: Session = Depends(get_db),
) -> dict:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Appareil introuvable")
    require_site_access(db, user, device.org_id)
    cmd = Command(device_id=device.id, type=CommandType.STOP_SHOW, payload=json.dumps({}))
    db.add(cmd)
    device.current_media_id = None
    device.player_state = "idle"
    playback_state.mark_queue_stopped(device.id)
    audit(db, "device.queue_stop", "device", device.id, user=user)
    db.commit()
    db.refresh(cmd)
    return {"command_id": cmd.id}


@router.post("/devices/{device_id}/commands", status_code=201)
def issue_command(
    device_id: str,
    body: CommandIn,
    request: Request,
    user: User = Depends(require_permission(Permission.DEVICE_COMMAND)),
    db: Session = Depends(get_db),
) -> CommandOut:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device introuvable")
    require_site_access(db, user, device.org_id)
    cmd = Command(
        device_id=device_id,
        type=body.type,
        payload=body.payload,
        issued_by_id=user.id,
    )
    db.add(cmd)
    db.commit()
    db.refresh(cmd)
    audit(db, "command.issue", "command", cmd.id, detail=body.type.value, user=user)
    db.commit()
    return CommandOut.model_validate(cmd)


@router.post("/devices/{device_id}/commands/{command_id}/ack")
def ack_command(
    device_id: str,
    command_id: str,
    body: CommandAck,
    device: Device = Depends(get_device_from_request),
    db: Session = Depends(get_db),
) -> dict:
    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Accès refusé")
    cmd = db.get(Command, command_id)
    if cmd is None or cmd.device_id != device_id:
        raise HTTPException(status_code=404, detail="Commande introuvable")
    cmd.status = CommandStatus.FAILED if body.error else CommandStatus.ACKED
    cmd.error = body.error
    cmd.acked_at = dt.datetime.now(dt.UTC)
    db.commit()
    if body.error:
        _add_event(db, device.org_id, device.site_id, device.id, "command_failed",
                   EventLevel.WARNING, f"Commande {cmd.type.value} échouée : {body.error}")
    db.commit()
    return {"status": "ok"}


def _device_status(device: Device, now: dt.datetime, grace: int) -> str:
    from elyon_api.deps import compute_device_status

    return compute_device_status(device, now, grace)


@router.get("/admin/devices/{device_id}/status")
def admin_device_status(
    device_id: str,
    request: Request,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
) -> dict:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device introuvable")
    require_site_access(db, user, device.org_id)
    settings = request.app.state.settings
    now = dt.datetime.now(dt.UTC)
    # Manifest version (latest)
    from sqlalchemy import func as _func

    from elyon_api.models import Manifest as _Manifest
    version = db.scalar(
        select(_func.max(_Manifest.version)).where(_Manifest.device_id == device.id)
    )
    computed = _device_status(device, now, settings.offline_grace_seconds)
    return {
        "device_id": device.id,
        "status": device.status.value,
        "computed_status": computed,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "screen_id": device.screen.id if device.screen else None,
        "manifest_version": version,
    }


@router.get("/admin/devices/{device_id}/commands")
def admin_list_commands(
    device_id: str,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
) -> list[CommandOut]:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device introuvable")
    require_site_access(db, user, device.org_id)
    commands = db.scalars(
        select(Command)
        .where(Command.device_id == device_id)
        .order_by(Command.created_at.desc())
        .limit(100)
    ).all()
    return [CommandOut.model_validate(c) for c in commands]


@router.get("/admin/devices/{device_id}/heartbeat")
def admin_heartbeat(
    device_id: str,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
) -> dict:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device introuvable")
    require_site_access(db, user, device.org_id)
    return {
        "status": "ok",
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "device_status": device.status.value,
        "player_state": device.player_state,
        "current_media_id": device.current_media_id,
    }


@router.get("/admin/devices/{device_id}/manifest")
def admin_manifest_preview(
    device_id: str,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
) -> dict:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device introuvable")
    require_site_access(db, user, device.org_id)
    from elyon_api.services.manifest import latest_manifest
    manifest = latest_manifest(db, device_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Aucun manifeste publié")
    return {
        "version": manifest.version,
        "payload": manifest.payload,
        "signature": manifest.signature,
        "published_at": manifest.published_at.isoformat(),
    }


@router.get("/admin/wall/preview/{media_id}")
def wall_media_preview(
    media_id: str,
    request: Request,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
):
    """Aperçu d'un média actuellement diffusé sur un écran (mur VNC).

    Contrairement à `/api/media/{id}/preview-file` (espace personnel isolé),
    cet endpoint expose uniquement les médias **diffusés** (présents dans un
    manifeste publié ou commandés via « Afficher ») — visible par tout
    utilisateur connecté du back-office, sans contourner l'isolation des
    bibliothèques privées.
    """
    media = db.get(Media, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Média introuvable")
    # Le média doit être en diffusion : présent dans un manifeste publié,
    # en cours d'affichage sur un device (heartbeat), ou via « Afficher ».
    in_manifest = db.scalar(
        select(func.count())
        .select_from(Manifest)
        .where(Manifest.payload.like(f'%{media_id}%'))
    )
    on_screen = db.scalar(
        select(func.count())
        .select_from(Device)
        .where(Device.current_media_id == media_id)
    )
    shown = db.scalar(
        select(func.count())
        .select_from(Command)
        .where(
            Command.type == CommandType.SHOW,
            Command.payload.like(f'%{media_id}%'),
        )
    )
    if not (in_manifest or on_screen or shown):
        raise HTTPException(status_code=404, detail="Média non diffusé")

    storage = build_storage(request.app.state.settings)
    if media.kind in (MediaKind.PDF, MediaKind.OFFICE) and media.pages_json:
        pages = json.loads(media.pages_json)
        if pages:
            return _serve_storage_file(storage, pages[0], "image/png")
    return _serve_storage_file(storage, media.storage_path, media.mime_type)


@router.get("/admin/wall/{device_id}/live")
def wall_device_live(device_id: str, request: Request):
    """Flux MJPEG « vrai direct » de ce que l'écran affiche.

    Re-fabrique une image à partir du média en cours de lecture
    (heartbeat du device) et la streame en multipart/x-mixed-replace :
    le navigateur met à jour l'image sans code JS ni polling. L'état
    ``current_media_id``/``player_state`` est relu à chaque frame — le
    flux suit la diffusion en temps réel (changement de média, blank…).
    Les vidéos sont pipées par un unique processus ffmpeg en temps réel
    (flux MJPEG continu) plutôt qu'une frame extraite à la demande :
    l'aperçu est fluide au lieu d'un diaporama ~2 i/s.
    """
    import asyncio

    settings = request.app.state.settings
    db_factory = request.app.state.session_factory

    def _part(payload: bytes, mime: str) -> bytes:
        return (
            b"--elyonframe\r\n"
            b"Content-Type: " + mime.encode() + b"\r\nContent-Length: "
            + str(len(payload)).encode() + b"\r\n\r\n" + payload + b"\r\n"
        )

    async def generate():
        # Pas d'en-tête initial : la première partie doit être une image,
        # sinon certains navigateurs refusent de rendre le <img> MJPEG.
        loop = asyncio.get_running_loop()
        while True:
            try:
                video = await loop.run_in_executor(
                    None, _live_video_state, db_factory, settings, device_id
                )
            except Exception:  # noqa: BLE001 — ne jamais casser le flux
                video = None
            if video is not None and _ffmpeg_available():
                path, seek, widgets = video
                sent = 0
                device = await loop.run_in_executor(
                    None, _device_from_factory, db_factory, device_id
                )
                dims = _screen_dims(device) if device is not None else None
                try:
                    async for jpeg in _video_mjpeg_parts(path, seek):
                        if widgets:
                            jpeg = await loop.run_in_executor(
                                None, _overlay_widgets_jpeg, jpeg, widgets, dims
                            )
                        yield _part(jpeg, "image/jpeg")
                        sent += 1
                        # Re-vérification ~0,7 s : si le média a changé
                        # (nouveau « Afficher », arrêt, blank…), on coupe le pipe.
                        if sent % 8 == 0:
                            cur = await loop.run_in_executor(
                                None, _live_video_state, db_factory, settings, device_id
                            )
                            if cur is None or cur[0] != path:
                                break
                except Exception:  # noqa: BLE001 — ne jamais casser le flux
                    pass
                if sent == 0:
                    # ffmpeg n'a rien produit (fichier corrompu…) : éviter
                    # une boucle chaude avant de réévaluer.
                    await asyncio.sleep(0.5)
                continue
            try:
                frame = await loop.run_in_executor(
                    None, _render_live_frame, db_factory, settings, device_id
                )
            except Exception:  # noqa: BLE001 — ne jamais casser le flux
                frame = None
            if frame is None:
                frame = _placeholder_png_bytes("Aperçu indisponible")
                mime = "image/png"
            else:
                mime = _frame_types.get(device_id, "image/jpeg")
            yield _part(frame, mime)
            # GIF animé : on tient la partie le temps que l'animation se joue
            # en boucle côté navigateur — une nouvelle partie trop fréquente
            # relancerait l'animation à zéro et l'image resterait figée sur
            # la première frame.
            await asyncio.sleep(10.0 if mime == "image/gif" else 0.4)

    from fastapi.responses import HTMLResponse, StreamingResponse

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=elyonframe",
        headers={"Cache-Control": "no-store"},
    )


def _video_duration(path: Path) -> float | None:
    """Durée de la vidéo (ffprobe), mise en cache par fichier."""
    import subprocess

    global _video_duration_cache
    cached = _video_duration_cache.get(str(path))
    if cached is not None:
        return cached[0]
    duration: float | None = None
    try:
        result = subprocess.run(  # noqa: S603
            [
                "ffprobe",
                "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=nw=1:nk=1",
                str(path),
            ],
            capture_output=True,
            timeout=10,
            check=False,
        )
        text = result.stdout.decode("ascii", "ignore").strip()
        if result.returncode == 0 and text:
            duration = float(text)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        duration = None
    _video_duration_cache[str(path)] = (duration, time.monotonic())
    return duration


def _video_frame(rel_abs_path: Path, seek_seconds: float = 3.0) -> bytes | None:
    """Extrait une image de la vidéo à la position de lecture donnée.

    La position suit la lecture réelle (début de lecture + temps écoulé,
    borné par la durée du fichier) : l'aperçu « vit » au lieu d'afficher une
    frame figée. Cache ~1 s par (fichier, position entière) pour éviter de
    décoder à chaque frame du flux MJPEG.
    """
    import subprocess
    import time as _time

    global _video_frame_cache
    seek = max(0.0, float(seek_seconds))
    duration = _video_duration(rel_abs_path)
    if duration and duration > 1:
        seek = seek % max(duration - 0.5, 0.5)
    key = f"{rel_abs_path}:{int(seek)}"
    cached = _video_frame_cache.get(key)
    now = _time.monotonic()
    if cached is not None and now - cached[1] < 1.0:
        return cached[0]
    try:
        result = subprocess.run(  # noqa: S603
            [
                "ffmpeg",
                "-ss", f"{seek:.3f}",
                "-i", str(rel_abs_path),
                "-frames:v", "1",
                "-f", "image2",
                "-vcodec", "mjpeg",
                "-q:v", "5",
                "-y",
                "pipe:1",
            ],
            capture_output=True,
            timeout=10,
            check=False,
        )
        frame = result.stdout if result.returncode == 0 and result.stdout else None
    except (OSError, subprocess.TimeoutExpired):
        frame = None
    if len(_video_frame_cache) > 512:
        _video_frame_cache.clear()
    _video_frame_cache[key] = (frame, now)
    return frame


_video_frame_cache: dict[str, tuple[bytes | None, float]] = {}
_video_duration_cache: dict[str, tuple[float | None, float]] = {}

_ffmpeg_ok: bool | None = None


def _ffmpeg_available() -> bool:
    global _ffmpeg_ok
    if _ffmpeg_ok is None:
        import shutil

        _ffmpeg_ok = shutil.which("ffmpeg") is not None
    return _ffmpeg_ok


def _find_player_marker(device: Device) -> tuple[Path, Path] | None:
    """Data-dir du player contenant `screen-frame.json` (lab / même machine)."""
    import os

    roots: list[Path] = []
    env_root = os.environ.get("ELYON_PLAYER_DATA_DIR")
    if env_root:
        roots.append(Path(env_root) / device.serial)
    # Conventions du lab (run-local/run-hosted) + data_dir par défaut.
    cwd = Path.cwd()
    # cwd est typiquement <racine>/apps/api → racine = 2 niveaux au-dessus.
    for base in (cwd.parents[1] / ".lab" if len(cwd.parents) > 1 else cwd / ".lab",
                 cwd.parents[0] / ".lab" if cwd.parents else cwd / ".lab",
                 cwd / ".lab", Path(".lab").resolve()):
        # « emu-rpi-preview » → player-preview (aperçu), « emu-rpi-1 » → player-1.
        suffix = device.serial.removeprefix("emu-rpi-")
        for sub in (f"player-{device.serial[-1]}", f"player-{suffix}", device.serial):
            roots.append(base / "hosted" / sub)
            roots.append(base / "local" / sub)
        roots.append(base / "qemu")
    roots.append(Path("/var/lib/elyon-player"))
    for root in roots:
        candidate = root / "screen-frame.json"
        if candidate.exists():
            return root, candidate
    return None


def _device_from_factory(db_factory, device_id: str) -> Device | None:
    with db_factory() as db:
        return db.get(Device, device_id)


def _live_video_state(
    db_factory, settings, device_id: str
) -> tuple[str, float, list[dict[str, Any]]] | None:
    """Vidéo en cours de lecture ? → (chemin absolu, position, widgets) ou None.

    Source de vérité prioritaire : le marqueur du player (`screen-frame.json`,
    écrit au démarrage de chaque lecture — immédiat, sans attendre le
    heartbeat de 30 s). Fallback : stockage serveur + suivi du moment où le
    média est devenu « en cours » (devices distants, pas de marqueur local).
    """
    with db_factory() as db:
        device = db.get(Device, device_id)
        if device is None:
            return None
        # Un écran explicitement éteint prime sur un marqueur éventuellement
        # périmé (le player ne réécrit pas son marqueur lors d'un blank).
        if device.player_state == "blank":
            return None
        marker = _find_player_marker(device)
        if marker is not None:
            _, marker_file = marker
            try:
                info = json.loads(marker_file.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                info = {}
            if info.get("video"):
                video_path = info.get("path")
                if video_path and Path(str(video_path)).exists():
                    try:
                        elapsed = max(0.0, time.time() - float(info.get("started_at")))
                    except (TypeError, ValueError):
                        elapsed = 0.0
                    duration = _video_duration(Path(str(video_path)))
                    # Marqueur périmé (vidéo terminée, item suivant pas encore
                    # démarré) : on retombe sur l'état base de données.
                    if not (duration and elapsed >= duration + 1.0):
                        seek = elapsed
                        if duration and duration > 1:
                            seek = min(seek, duration - 0.5)
                        return str(video_path), seek, _device_widgets(device)
                else:
                    return None  # fichier du player plus disponible
            elif info:  # marqueur valide mais non vidéo → image/GIF à l'écran
                return None
        # Fallback : rendu côté serveur depuis le stockage.
        if device.player_state != "playing":
            return None
        media = (
            db.get(Media, device.current_media_id)
            if device.current_media_id
            else None
        )
        if media is None or media.kind != MediaKind.VIDEO:
            return None
        rel = media.storage_path
        storage = build_storage(settings)
        to_abs = getattr(storage, "_abs", None)
        if to_abs is None:
            return None
        abs_path = Path(to_abs(rel))
        if not abs_path.exists():
            return None
        now = time.monotonic()
        tracked = _video_start.get(device.id)
        if tracked is None or tracked[0] != media.id:
            _video_start[device.id] = (media.id, now)
            seek = 0.0
        else:
            seek = now - tracked[1]
        return str(abs_path), seek, _device_widgets(device)


async def _video_mjpeg_parts(path: str, start_seek: float):
    """JPEG complets d'un flux MJPEG continu en temps réel.

    Un unique processus ffmpeg décode la vidéo à vitesse native (`-re`) et
    la pipe en MJPEG ; les frames sont découpées sur les bornes JPEG
    (FFD8…FFD9). Sortie plafonnée à 15 i/s et redimensionnée à 640 px pour
    garder l'aperçu léger sur le réseau.
    """
    import asyncio

    loop = asyncio.get_running_loop()
    duration = await loop.run_in_executor(None, _video_duration, Path(path))
    seek = max(0.0, float(start_seek))
    if duration and duration > 1:
        # Position modulo la durée : l'aperçu boucle comme la lecture réelle.
        seek = seek % max(duration - 0.5, 0.5)
    while True:
        proc = await asyncio.create_subprocess_exec(
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-re", "-ss", f"{seek:.3f}", "-i", path,
            "-an",
            "-vf", "fps=15,scale=min(640\\,iw):-2",
            "-f", "image2pipe", "-vcodec", "mjpeg", "-q:v", "5",
            "pipe:1",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        seek = 0.0  # les tours suivants repartent du début (boucle)
        buf = b""
        try:
            assert proc.stdout is not None
            while True:
                chunk = await proc.stdout.read(65536)
                if not chunk:
                    break
                buf += chunk
                while True:
                    soi = buf.find(b"\xff\xd8")
                    if soi == -1:
                        buf = b""
                        break
                    eoi = buf.find(b"\xff\xd9", soi + 2)
                    if eoi == -1:
                        if soi > 0:
                            buf = buf[soi:]
                        break
                    yield buf[soi : eoi + 2]
                    buf = buf[eoi + 2 :]
        finally:
            proc.terminate()
            try:
                await proc.wait()
            except Exception:  # noqa: BLE001
                pass
        # Fin du fichier : on boucle immédiatement sur la vidéo.
        await asyncio.sleep(0.1)


def _render_live_frame(db_factory, settings, device_id: str) -> bytes | None:
    """Image JPEG de la lecture courante du device (thread worker).

    Priorité à la **capture du player** (`screen-frame.jpg` écrite par le
    moteur de lecture, même machine en lab) : c'est exactement ce qui est
    affiché, y compris vidéos et contenus défaillants. Fallback : image du
    média courant (frame ffmpeg pour les vidéos).
    """
    import io as _io
    from pathlib import Path as _Path

    from PIL import Image

    with db_factory() as db:
        device = db.get(Device, device_id)
        if device is None:
            return None
        state = device.player_state
        media = db.get(Media, device.current_media_id) if device.current_media_id else None
        if state == "blank":
            return _placeholder_png_bytes("Écran éteint")
        if state != "playing" or media is None:
            return _placeholder_png_bytes("Écran en attente")
        storage = build_storage(settings)

        # 1) Capture du player (rendu réel) — lab hébergé / même machine.
        agent_frame = _player_frame(device, media)
        if agent_frame is not None:
            return agent_frame

        # 2) Fallback : rendu côté serveur à partir du média courant.
        rel = media.storage_path
        if media.kind in (MediaKind.PDF, MediaKind.OFFICE) and media.pages_json:
            pages = json.loads(media.pages_json)
            if pages:
                rel = pages[0]
        if not storage.exists(rel):
            return _placeholder_png_bytes("Fichier indisponible")
        try:
            if media.kind == MediaKind.VIDEO:
                # LocalStorage expose _abs (chemin réel sur disque) — requis
                # pour ffmpeg ; les backends distants retombent sur le
                # placeholder.
                to_abs = getattr(storage, "_abs", None)
                if to_abs is None:
                    return _placeholder_png_bytes("Vidéo en lecture")
                abs_path = _Path(to_abs(rel))
                # Sans horodatage du player : on suit la position depuis le
                # moment où ce média est devenu « en cours » (côté serveur).
                import time as _time

                now = _time.monotonic()
                tracked = _video_start.get(device.id)
                if tracked is None or tracked[0] != media.id:
                    _video_start[device.id] = (media.id, now)
                    seek = 0.0
                else:
                    seek = now - tracked[1]
                frame = _video_frame(abs_path, seek_seconds=seek)
                if frame:
                    return frame
                return _placeholder_png_bytes("Vidéo en lecture")
            with storage.open_read(rel) as f:
                data = f.read()
            img: Image.Image = Image.open(_io.BytesIO(data)).convert("RGB")
            widgets = _device_widgets(device)
            dims = _screen_dims(device)
            if widgets and dims:
                img = _fit_on_canvas(img, dims[0], dims[1])
                img = _compose_widget_bar_server(img, widgets, _device_site_tz(device))
            # Plafond de taille pour le flux MJPEG (pages PDF 120 dpi = 1 Mo+).
            img.thumbnail((1280, 1280))
            buf = _io.BytesIO()
            img.save(buf, "JPEG", quality=70)
            return buf.getvalue()
        except Exception:  # noqa: BLE001
            return _placeholder_png_bytes("Aperçu indisponible")


def _player_frame(device: Device, media: Media) -> bytes | None:
    """Capture écrite par le moteur de lecture (screen-frame.jpg), si dispo.

    Le chemin du data-dir du player est déduit du serial (lab hébergé :
    .lab/hosted/player-1) ou lu depuis l'environnement ELYON_PLAYER_DATA_DIR.
    """
    import time as _time

    global _player_frame_cache
    cache_key = device.id + ":" + (device.current_media_id or "")
    cached = _player_frame_cache.get(cache_key)
    now = _time.monotonic()
    if cached is not None and now - cached[1] < 1.0:
        return cached[0]

    frame: bytes | None = None
    marker = _find_player_marker(device)
    if marker is not None:
        root, marker_file = marker
        try:
            info = json.loads(marker_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            info = {}
        frame_file = root / "screen-frame.jpg"
        if info.get("video"):
            # Vidéo : le player indique le fichier source ET l'heure de début
            # de lecture → frame extraite à la position courante (aperçu vivant).
            video_path = info.get("path")
            if video_path and Path(str(video_path)).exists():
                try:
                    seek = max(0.0, _time.time() - float(info.get("started_at")))
                except (TypeError, ValueError):
                    seek = 3.0
                frame = _video_frame(Path(str(video_path)), seek_seconds=seek)
        elif frame_file.exists():
            try:
                frame = frame_file.read_bytes()
            except OSError:
                frame = None
    if frame is not None:
        # Un GIF copié tel quel est servi en image/gif (animation conservée) ;
        # le type réel est renvoyé par _live_frame_type côté flux.
        _frame_types[device.id] = (
            "image/gif" if frame[:4] == b"GIF8" else "image/jpeg"
        )
    _player_frame_cache[cache_key] = (frame, now)
    return frame


_frame_types: dict[str, str] = {}


_player_frame_cache: dict[str, tuple[bytes | None, float]] = {}

# device_id → (media_id, monotonic_start) : position de lecture estimée pour
# le rendu vidéo côté serveur (fallback sans capture du player).
_video_start: dict[str, tuple[str, float]] = {}

# Curseur + gel d'auto-enchaînement (module partagé, voir playback_state).


def _queue_advance_if_needed(db: Session, device: Device) -> None:
    """Enchaîne automatiquement sur le média suivant de la file.

    Appelé à chaque heartbeat : si le média de tête est joué depuis plus
    longtemps que son seuil (vidéo : durée réelle ; image : 10 s par défaut),
    le média suivant de la file passe en SHOW.
    """
    if device.player_state != "playing" or not device.current_media_id:
        return
    if not playback_state.auto_advance_allowed(device.id):
        return
    items = _device_queue_items(device)
    if len(items) < 2 or items[0]["media_id"] != device.current_media_id:
        return
    now = time.monotonic()
    cursor = playback_state.queue_cursor.get(device.id)
    if cursor is None or cursor[0] != device.current_media_id:
        # Nouvelle lecture : calculer le seuil de durée.
        threshold: float | None = 10.0  # image sans durée explicite
        media = db.get(Media, device.current_media_id)
        if media is not None and media.kind == MediaKind.VIDEO:
            settings = None  # durée via cache ffprobe ; abs du stockage local
            try:
                from elyon_api.config import Settings as _S
                from elyon_api.services.storage import LocalStorage as _LS
                storage = _LS(_S().media_storage_root)
                to_abs = getattr(storage, "_abs", None)
                if to_abs is not None:
                    threshold = _video_duration(to_abs(media.storage_path))
            except Exception:  # noqa: BLE001
                threshold = None
            if threshold is None:
                threshold = 30.0
        playback_state.queue_cursor[device.id] = (device.current_media_id, now, threshold)
        return
    _, started, threshold = cursor
    if threshold is None or now - started < threshold:
        return
    # Fin de lecture : rotation de la file + SHOW du suivant.
    next_id = items[1]["media_id"]
    media = db.get(Media, next_id)
    if media is None:
        return
    items = items[1:] + [items[0]]
    device.queue_json = json.dumps(items)
    for stale in db.scalars(
        select(Command).where(
            Command.device_id == device.id,
            Command.type == CommandType.SHOW,
            Command.status == CommandStatus.PENDING,
        )
    ):
        stale.status = CommandStatus.FAILED
        stale.error = "Remplacé (auto-enchaînement)"
    cmd = Command(
        device_id=device.id,
        type=CommandType.SHOW,
        payload=json.dumps(
            {"media_id": media.id, "name": media.name, "kind": media.kind.value}
        ),
    )
    db.add(cmd)
    device.current_media_id = media.id
    device.player_state = "playing"
    playback_state.queue_cursor[device.id] = (media.id, now, 10.0)
    audit(db, "device.queue_auto_next", "device", device.id, detail=media.name)


def _placeholder_png_bytes(text: str) -> bytes:
    """Image de secours : fond sombre + texte (générée côté serveur)."""
    import io as _io

    from PIL import Image, ImageDraw

    img = Image.new("RGB", (640, 360), (11, 18, 32))
    draw = ImageDraw.Draw(img)
    draw.rectangle([8, 8, 631, 351], outline=(51, 65, 85), width=2)
    draw.text((320 - len(text) * 4, 172), text, fill=(148, 163, 184))
    buf = _io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _serve_storage_file(storage, rel_path: str, mime_type: str):
    if not storage.exists(rel_path):
        raise HTTPException(status_code=404, detail="Fichier manquant")
    from fastapi.responses import HTMLResponse, Response as _Response

    with storage.open_read(rel_path) as f:
        data = f.read()
    return _Response(content=data, media_type=mime_type)


@router.get("/admin/wall")
def admin_wall(
    request: Request,
    user: User = Depends(require_permission(Permission.DEVICE_VIEW)),
    db: Session = Depends(get_db),
) -> list[dict]:
    """Mur d'écrans : état de lecture de chaque Raspberry (émulé ou réel)."""
    settings = request.app.state.settings
    now = dt.datetime.now(dt.UTC)
    stmt = select(Device).order_by(Device.is_preview.desc(), Device.name)
    if user.role != Role.SUPERADMIN:
        stmt = stmt.where(Device.org_id == user.org_id)
    items = []
    for device in db.scalars(stmt):
        media = db.get(Media, device.current_media_id) if device.current_media_id else None
        site = device.site
        items.append(
            {
                "device_id": device.id,
                "name": device.name,
                "serial": device.serial,
                "site_id": site.id if site else None,
                "site_name": site.name if site else None,
                "is_preview": bool(device.is_preview),
                "status": device.status.value,
                "computed_status": _device_status(device, now, settings.offline_grace_seconds),
                "player_state": device.player_state,
                "current_media_id": device.current_media_id,
                "current_media_name": media.name if media else None,
                "current_media_kind": media.kind.value if media else None,
                "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
                "screen_id": device.screen.id if device.screen else None,
                **dict(
                    zip(("ticker_text", "ticker_speed"), _screen_ticker(device))
                ),
            }
        )
    return items



IDLE_SCREEN_HTML = """<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<title>Affichage en préparation</title>
<style>
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; overflow: hidden; }
  body {
    display: flex; align-items: center; justify-content: center;
    font-family: -apple-system, "Segoe UI", Roboto, sans-serif;
    background: linear-gradient(120deg, #0f172a, #1e1b4b, #0c4a6e, #1e1b4b, #0f172a);
    background-size: 300% 300%;
    animation: pan 18s ease-in-out infinite;
    color: #e2e8f0;
  }
  @keyframes pan { 0%,100% { background-position: 0% 50%; } 50% { background-position: 100% 50%; } }
  .orb { position: fixed; border-radius: 50%; filter: blur(60px); opacity: .35; animation: orb 12s ease-in-out infinite; }
  .orb.a { width: 24vmax; height: 24vmax; left: 8%; top: 15%; background: #0ea5e9; }
  .orb.b { width: 30vmax; height: 30vmax; right: 10%; top: 55%; background: #6366f1; animation-delay: 3s; }
  .orb.c { width: 20vmax; height: 20vmax; left: 45%; bottom: 10%; background: #22d3ee; animation-delay: 6s; }
  @keyframes orb { 0%,100% { transform: translate(0,0) scale(1); } 50% { transform: translate(24px,-18px) scale(1.15); } }
  h1 { font-size: clamp(20px, 4vw, 48px); font-weight: 600; letter-spacing: .04em;
       animation: pulse 3.2s ease-in-out infinite; }
  @keyframes pulse { 0%,100% { opacity: .65; } 50% { opacity: 1; } }
  .ticker { position: fixed; bottom: 0; left: 0; right: 0; overflow: hidden;
            background: rgba(0,0,0,.7); padding: .6rem 1rem; font-size: 16px; white-space: nowrap; }
  .ticker span { display: inline-block; position: relative; animation: slide 14s linear infinite; }
  @keyframes slide { from { left: -100%; } to { left: 100%; } }
  @media (prefers-reduced-motion: reduce) { body, .orb, h1, .ticker span { animation: none !important; } }
</style>
</head>
<body>
  <span class="orb a"></span><span class="orb b"></span><span class="orb c"></span>
  <h1>Affichage en préparation</h1>
  __TICKER__
</body>
</html>
"""


_widget_feed_cache: dict[str, tuple[dict[str, Any], float]] = {}


def _widget_feed_entry(kind: str, params: dict[str, Any]) -> dict[str, Any] | None:
    """Donnée de widget (météo/RSS) avec cache 5 min, jamais bloquante."""
    key = kind + ":" + str(params.get("city") or params.get("url") or "")
    cached = _widget_feed_cache.get(key)
    now = time.monotonic()
    if cached and now - cached[1] < 300:
        return cached[0]
    data: dict[str, Any] | None = None
    try:
        if kind == "weather":
            data = widget_feed.fetch_weather(str(params.get("city") or ""))
        elif kind == "rss":
            data = widget_feed.fetch_rss(str(params.get("url") or ""))
    except Exception:  # noqa: BLE001 — un feed indisponible ne casse pas l'aperçu
        data = None
    if data is not None:
        _widget_feed_cache[key] = (data, now)
    return cached[0] if (data is None and cached) else data


def _device_widgets(device: Device) -> list[dict[str, Any]]:
    """Widgets visibles de l'écran du device (pour la composition serveur)."""
    screen = device.screen
    if screen is None or not screen.widgets_json:
        return []
    try:
        widgets = json.loads(screen.widgets_json)
    except (ValueError, TypeError):
        return []
    if not isinstance(widgets, list):
        return []
    return [
        w
        for w in widgets
        if isinstance(w, dict) and w.get("visible", True)
    ]


def _load_display_font(size: int):
    """Police d'affichage : DejaVu (accents) si présente, sinon la police PIL."""
    from PIL import ImageFont

    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=size
        )
    except (OSError, ImportError):
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()



def _screen_dims(device: Device) -> tuple[int, int] | None:
    screen = device.screen
    if screen is None:
        return None
    try:
        w, h = int(screen.width), int(screen.height)
        return (w, h) if w > 0 and h > 0 else None
    except (TypeError, ValueError):
        return None


def _fit_on_canvas(img: "Image.Image", width: int, height: int) -> "Image.Image":
    """Cadre le média dans la taille de l'écran (object-contain, fond noir).

    Les widgets sont ensuite composés sur ce canevas : taille et position
    constantes quel que soit le média affiché.
    """
    from PIL import Image as _Image

    if (img.width, img.height) == (width, height):
        return img
    canvas = _Image.new("RGB", (width, height), (8, 10, 14))
    scale = min(width / img.width, height / img.height)
    new_size = (max(1, int(img.width * scale)), max(1, int(img.height * scale)))
    resized = img.resize(new_size)
    canvas.paste(resized, ((width - new_size[0]) // 2, (height - new_size[1]) // 2))
    return canvas


def _device_site_tz(device: Device) -> str:
    try:
        tz = device.screen.site.timezone if device.screen and device.screen.site else None
        return tz or "Europe/Paris"
    except Exception:  # noqa: BLE001
        return "Europe/Paris"


def _compose_widget_bar_server(
    img: "Image.Image", widgets: list[dict[str, Any]], site_tz: str = "Europe/Paris"
) -> "Image.Image":
    """Incruste les widgets d'information sur une image (aperçu serveur).

    Version légère du rendu du player : météo, horloge, texte, ticker
    défilant (animé d'une frame à l'autre via l'horodatage).
    """
    from PIL import Image, ImageDraw, ImageFont

    if not widgets:
        return img
    width, height = img.size
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    base_size = max(12, height // 30)
    small_size = max(11, height // 40)
    pad_x, pad_y, margin = max(6, width // 150), max(4, height // 90), max(8, width // 100)
    now = dt.datetime.now()
    band_bottom: int | None = None  # bas du bandeau haut (météo)
    for widget in widgets:
        kind = str(widget.get("type") or "")
        position = str(widget.get("position") or "bottom-left")
        scale = {"small": 1.0, "medium": 1.5, "large": 2.2}.get(
            str((widget.get("params") or {}).get("size") or "medium"), 1.5
        )
        params = widget.get("params") or {}
        if kind == "weather":
            city = str(params.get("city") or "").strip() or "Météo"
            entry = _widget_feed_entry("weather", params) or {}
            temp = entry.get("temperature")
            line1 = f"{city} · {temp:.0f}°C" if isinstance(temp, (int, float)) else city
            fc = entry.get("forecast") or []
            line2 = "  ".join(
                f"{FR_DAYS_W[i]} {round(f.get('max', 0))}°/{round(f.get('min', 0))}°"
                for i, f in enumerate(fc[:4])
                if isinstance(f, dict)
            )
            text = line1 if not line2 else line1 + "\n" + line2
        elif kind == "clock":
            fmt = str(params.get("format") or "HH:MM")
            if str(params.get("tz") or "site") == "utc":
                from datetime import timezone as _tz

                now_w = dt.datetime.now(_tz.utc)
            else:
                try:
                    from zoneinfo import ZoneInfo

                    now_w = dt.datetime.now(ZoneInfo(site_tz))
                except Exception:  # noqa: BLE001
                    now_w = now
            text = now_w.strftime("%H:%M:%S" if fmt == "HH:MM:SS" else "%H:%M")
        elif kind in ("text", "ticker"):
            text = str(params.get("text") or "")
        elif kind == "rss":
            entry = _widget_feed_entry("rss", params) or {}
            items = [str(i) for i in (entry.get("items") or []) if str(i).strip()]
            text = "  •  ".join(items[:5]) if items else "RSS"
        else:
            continue
        if not text:
            continue
        font_size = int(base_size * scale)
        font = _load_display_font(font_size)
        small = _load_display_font(max(11, int(small_size * scale)))
        if position == "bottom-ticker":
            _draw_server_ticker(draw, img, text, font, max(11, int(small_size * scale)), now, height)
            continue
        f = font
        try:
            bbox = draw.multiline_textbbox((0, 0), text, font=f)
        except Exception:  # noqa: BLE001
            continue
        text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        if text_w <= 0:
            continue
        bar_w, bar_h = text_w + 2 * pad_x, text_h + 2 * pad_y
        if position == "top-band":
            draw.rounded_rectangle(
                (0, margin, width, margin + bar_h), radius=max(4, bar_h // 3), fill=(0, 0, 0, 178)
            )
            draw.multiline_text(
                ((width - text_w) // 2, margin + pad_y - bbox[1]), text, font=f, fill=(255, 255, 255, 255)
            )
            band_bottom = margin + bar_h
            continue
        if position == "center":
            # Troncature : le texte doit tenir dans la largeur (ellipsis).
            max_w = width - 2 * margin - 2 * pad_x
            fitted = text
            try:
                while fitted and draw.textlength(fitted, font=f) > max_w:
                    fitted = fitted[:-2].rstrip() + "…"
            except Exception:  # noqa: BLE001
                pass
            try:
                fb = draw.multiline_textbbox((0, 0), fitted, font=f)
            except Exception:  # noqa: BLE001
                continue
            fw, fh = fb[2] - fb[0], fb[3] - fb[1]
            draw.rounded_rectangle(
                ((width - fw) // 2 - pad_x, (height - fh) // 2 - pad_y,
                 (width + fw) // 2 + pad_x, (height + fh) // 2 + pad_y),
                radius=max(4, (fh + 2 * pad_y) // 3),
                fill=(0, 0, 0, 178),
            )
            draw.multiline_text(
                ((width - fw) // 2 - fb[0], (height - fh) // 2 - fb[1]),
                fitted, font=f, fill=(255, 255, 255, 255),
            )
            continue
        top = position.startswith("top-")
        if position.endswith("-center"):
            bar_x = (width - bar_w) // 2
        elif position.endswith("-right"):
            bar_x = width - bar_w - margin
        else:
            bar_x = margin
        # Horloge/widget haut : sous le bandeau météo s'il existe.
        bar_y = (band_bottom + 4) if (top and band_bottom is not None) else (margin if top else height - bar_h - margin)
        draw.rounded_rectangle(
            (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
            radius=max(4, bar_h // 3),
            fill=(0, 0, 0, 178),
        )
        draw.multiline_text(
            (bar_x + pad_x - bbox[0], bar_y + pad_y - bbox[1]), text, font=f, fill=(255, 255, 255, 255)
        )
    from PIL import Image as _Image

    return _Image.alpha_composite(img.convert("RGBA"), overlay).convert("RGB")


FR_DAYS_W = ["dim", "lun", "mar", "mer", "jeu", "ven", "sam"]


def re_sub_html(raw: str) -> str:
    import html as _html
    import re as _re

    return _html.unescape(_re.sub(r"<[^>]+>", " ", raw))


def _draw_server_ticker(
    draw: Any, img: "Image.Image", text: str, font: Any, small_size: int, now: dt.datetime, height: int
) -> None:
    width = img.size[0]
    bar_h = max(18, height // 22)
    draw.rectangle((0, height - bar_h, width, height), fill=(0, 0, 0, 210))
    try:
        tw = draw.textlength(text, font=font)
    except Exception:  # noqa: BLE001
        tw = len(text) * small_size
    offset = (now.timestamp() * 60) % max(tw + width, 1)
    x = width - offset
    draw.text((x, height - bar_h + (bar_h - small_size) // 2 - 2), text, font=font, fill=(255, 255, 255, 255))
    if x + tw < width:
        draw.text(
            (x + tw + width // 10, height - bar_h + (bar_h - small_size) // 2 - 2),
            text, font=font, fill=(255, 255, 255, 255),
        )


def _overlay_widgets_jpeg(
    jpeg: bytes, widgets: list[dict[str, Any]], dims: tuple[int, int] | None = None
) -> bytes:
    """Applique la barre de widgets sur une frame JPEG (aperçu vidéo).

    `dims` = taille de l'écran : la frame est cadrée dans le canevas écran
    avant composition (widgets à taille/position constantes).
    """
    if not widgets:
        return jpeg
    import io as _io

    from PIL import Image

    try:
        img = Image.open(_io.BytesIO(jpeg)).convert("RGB")
        if dims:
            img = _fit_on_canvas(img, dims[0], dims[1])
        composed = _compose_widget_bar_server(img, widgets)
        composed.thumbnail((1280, 1280))
        out = _io.BytesIO()
        composed.save(out, "JPEG", quality=70)
        return out.getvalue()
    except Exception:  # noqa: BLE001
        return jpeg


def _screen_ticker(device: Device) -> tuple[str | None, str | None]:
    """Texte du widget « texte déroulant » (ou texte libre) de l'écran du device.

    Sert à l'écran d'attente : le ticker reste visible même sans diffusion.
    """
    screen = device.screen
    if screen is None or not screen.widgets_json:
        return None, None
    try:
        widgets = json.loads(screen.widgets_json)
    except (ValueError, TypeError):
        return None, None
    if not isinstance(widgets, list):
        return None, None
    for widget in widgets:
        if not isinstance(widget, dict) or not widget.get("visible", True):
            continue
        position = str(widget.get("position") or "")
        kind = str(widget.get("type") or "")
        if position == "bottom-ticker" and kind in ("ticker", "text", "rss"):
            params = widget.get("params") or {}
            text = str(params.get("text") or "").strip()
            if kind == "ticker" and text:
                return text, str(params.get("speed") or "normal")
            if kind == "text" and text:
                return text, None
            if kind == "rss":
                entry = _widget_feed_entry("rss", params) or {}
                items = [str(i) for i in (entry.get("items") or []) if str(i).strip()]
                if items:
                    return "  •  ".join(items[:5]), None
    return None, None


@router.get("/idle-screen", response_class=HTMLResponse)
def idle_screen(text: str | None = None, speed: str = "normal") -> HTMLResponse:
    """Écran d'attente : animation sobre + « Affichage en préparation ».

    Page autonome (CSS inline) destinée aux kiosques Chromium et au mur.
    `text` : texte déroulant optionnel affiché en bas de l'écran.
    """
    duration = {"slow": "30s", "fast": "7s"}.get(speed, "14s")
    ticker_html = ""
    if text:
        safe = html_mod.escape(text)
        ticker_html = (
            f'<div class="ticker"><span style="animation-duration:{duration}">{safe}</span></div>'
        )
    return HTMLResponse(IDLE_SCREEN_HTML.replace("__TICKER__", ticker_html))


def _audit_names(db: Session, rows: Sequence[AuditLog]) -> dict[str, str]:
    """Résout les identifiants techniques en noms lisibles (1 requête/classe)."""
    from elyon_api.models import Playlist, Screen, Site, Team

    user_ids = {r.user_id for r in rows if r.user_id}
    device_ids = {r.resource_id for r in rows if r.resource_type == "device" and r.resource_id}
    playlist_ids = {r.resource_id for r in rows if r.resource_type == "playlist" and r.resource_id}
    site_ids = {r.resource_id for r in rows if r.resource_type == "site" and r.resource_id}
    screen_ids = {r.resource_id for r in rows if r.resource_type == "screen" and r.resource_id}
    team_ids = {r.resource_id for r in rows if r.resource_type == "team" and r.resource_id}
    media_ids = {r.resource_id for r in rows if r.resource_type == "media" and r.resource_id}

    names: dict[str, str] = {}
    if user_ids:
        for u in db.scalars(select(User).where(User.id.in_(user_ids))):
            names[u.id] = u.full_name or u.email
    if device_ids:
        for d in db.scalars(select(Device).where(Device.id.in_(device_ids))):
            names[d.id] = d.name
    if playlist_ids:
        for p in db.scalars(select(Playlist).where(Playlist.id.in_(playlist_ids))):
            names[p.id] = p.name
    if site_ids:
        for site_row in db.scalars(select(Site).where(Site.id.in_(site_ids))):
            names[site_row.id] = site_row.name
    if screen_ids:
        for screen_row in db.scalars(select(Screen).where(Screen.id.in_(screen_ids))):
            names[screen_row.id] = screen_row.name
    if team_ids:
        for t in db.scalars(select(Team).where(Team.id.in_(team_ids))):
            names[t.id] = t.name
    if media_ids:
        for m in db.scalars(select(Media).where(Media.id.in_(media_ids))):
            names[m.id] = m.name
    return names


@router.get("/audit/logs")
def list_audit_logs(
    action: str | None = None,
    resource_type: str | None = None,
    user_id: str | None = None,
    limit: int = 10,
    offset: int = 0,
    user: User = Depends(require_permission(Permission.AUDIT_VIEW)),
    db: Session = Depends(get_db),
) -> dict:
    """Journal d'audit paginé (défaut 10/page, max 100) + noms lisibles."""
    page_size = min(max(limit, 1), 100)
    stmt = select(AuditLog).order_by(AuditLog.created_at.desc())
    if user.role != Role.SUPERADMIN:
        stmt = stmt.where(AuditLog.org_id == user.org_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if resource_type:
        stmt = stmt.where(AuditLog.resource_type == resource_type)
    if user_id:
        stmt = stmt.where(AuditLog.user_id == user_id)
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.offset(max(offset, 0)).limit(page_size)).all()
    names = _audit_names(db, rows)
    items = []
    for a in rows:
        item = AuditLogOut.model_validate(a)
        item.resource_name = names.get(a.resource_id or "")
        item.user_name = names.get(a.user_id or "")
        items.append(item)
    return {
        "items": items,
        "total": total,
        "limit": page_size,
        "offset": max(offset, 0),
    }


@router.get("/admin/playback/export")
def export_playback(
    device_id: str | None = None,
    from_date: str | None = None,
    to_date: str | None = None,
    user: User = Depends(require_permission(Permission.DEVICE_VIEW)),
    db: Session = Depends(get_db),
):
    """Export CSV de la preuve de lecture (proof-of-play).

    Filtres : `device_id`, `from_date`/`to_date` (ISO). Colonnes : horodatage,
    appareil (nom), média (nom), état. Les noms arrivent du serveur : le CSV
    neutralise les formules pour éviter l'injection dans les tableurs.
    """
    from elyon_api.models import Media as _Media
    from elyon_api.models import PlaybackEvent as _PE

    stmt = select(_PE).order_by(_PE.recorded_at.desc())
    if user.role != Role.SUPERADMIN:
        stmt = stmt.where(_PE.org_id == user.org_id)
    if device_id:
        stmt = stmt.where(_PE.device_id == device_id)
    if from_date:
        try:
            stmt = stmt.where(_PE.recorded_at >= dt.datetime.fromisoformat(from_date))
        except ValueError:
            raise HTTPException(status_code=422, detail="from_date invalide") from None
    if to_date:
        try:
            stmt = stmt.where(_PE.recorded_at <= dt.datetime.fromisoformat(to_date))
        except ValueError:
            raise HTTPException(status_code=422, detail="to_date invalide") from None

    rows = db.scalars(stmt.limit(20000)).all()
    device_ids = {r.device_id for r in rows}
    device_names = {
        d.id: d.name
        for d in db.scalars(select(Device).where(Device.id.in_(device_ids)))
    }
    media_ids = {r.media_id for r in rows if r.media_id}
    media_names = {
        m.id: m.name
        for m in db.scalars(select(_Media).where(_Media.id.in_(media_ids)))
    }

    def _csv_safe(value: object) -> str:
        s = "" if value is None else str(value)
        if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
            return "'" + s
        return s

    lines = ["horodatage,appareil,media,etat"]
    for r in rows:
        lines.append(
            ",".join(
                _csv_safe(x)
                for x in (
                    r.recorded_at.isoformat(),
                    device_names.get(r.device_id, r.device_id),
                    media_names.get(r.media_id or "", r.media_id or ""),
                    r.state,
                )
            )
        )
    return Response(
        content="\n".join(lines).encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="proof-of-play.csv"'},
    )


@router.get("/dashboard")
def dashboard(
    request: Request,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
) -> dict:
    settings = request.app.state.settings
    now = dt.datetime.now(dt.UTC)
    org_where = [] if user.role == Role.SUPERADMIN else [Device.org_id == user.org_id]
    devices = db.scalars(select(Device).where(*org_where)).all()
    online = sum(
        1 for d in devices if _device_status(d, now, settings.offline_grace_seconds) == "online"
    )
    pending = sum(1 for d in devices if d.status == DeviceStatus.PENDING)
    media_filter = [] if user.role == Role.SUPERADMIN else [Media.org_id == user.org_id]
    media_count = db.scalar(select(func.count()).select_from(Media).where(*media_filter))
    media_ready = db.scalar(
        select(func.count())
        .select_from(Media)
        .where(*media_filter, Media.status == MediaStatus.READY)
    )
    media_bytes = db.scalar(
        select(func.coalesce(func.sum(Media.size_bytes), 0))
        .select_from(Media)
        .where(*media_filter)
    )
    events_filter = [] if user.role == Role.SUPERADMIN else [Event.org_id == user.org_id]
    events_24h = db.scalar(
        select(func.count())
        .select_from(Event)
        .where(*events_filter, Event.created_at >= now - dt.timedelta(hours=24))
    )
    events_warning_24h = db.scalar(
        select(func.count())
        .select_from(Event)
        .where(
            *events_filter,
            Event.created_at >= now - dt.timedelta(hours=24),
            Event.level.in_([EventLevel.WARNING, EventLevel.ERROR]),
        )
    )
    events_stmt = select(Event).order_by(Event.created_at.desc()).limit(8)
    if user.role != Role.SUPERADMIN:
        events_stmt = events_stmt.where(Event.org_id == user.org_id)
    recent_events = [EventOut.model_validate(e) for e in db.scalars(events_stmt)]
    return {
        "devices_total": len(devices),
        "devices_online": online,
        "devices_offline": max(len(devices) - online, 0),
        "devices_pending": pending,
        "media_count": media_count or 0,
        "media_ready": media_ready or 0,
        "media_bytes": media_bytes or 0,
        "events_24h": events_24h or 0,
        "events_warning_24h": events_warning_24h or 0,
        "recent_events": recent_events,
        "server_time": now.isoformat(),
    }