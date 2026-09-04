from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from elyon_api.db import get_db
from elyon_api.models import (
    Command,
    CommandStatus,
    CommandType,
    Device,
    DeviceStatus,
    Media,
    Playlist,
    PlaylistItem,
)

router = APIRouter(prefix="/api/trigger", tags=["triggers"])


@router.post("/{device_id}/show")
async def trigger_show(
    device_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Déclenche une diffusion « Afficher » depuis un système externe (alarme).

    Authentifié par le secret partagé `ELYON_TRIGGER_SECRET` (en-tête
    `X-Trigger-Secret`). Permet d'interrompre la playlist d'un écran avec un
    média précis, sans passer par le back-office — par ex. message
    d'évacuation, alerte météo, GMAO.
    """
    settings = request.app.state.settings
    if not settings.trigger_secret:
        raise HTTPException(status_code=404, detail="Trigger non configuré")
    supplied = request.headers.get("X-Trigger-Secret", "")
    if supplied != settings.trigger_secret:
        raise HTTPException(status_code=403, detail="Secret invalide")

    body = await request.json()
    media_id = body.get("media_id") or body.get("media")
    duration = body.get("duration_seconds")
    if not media_id:
        raise HTTPException(status_code=422, detail="media_id requis")

    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Appareil introuvable")
    if device.status != DeviceStatus.APPROVED:
        raise HTTPException(status_code=409, detail="Appareil indisponible")

    media = db.get(Media, media_id)
    if media is None or media.org_id != device.org_id:
        raise HTTPException(status_code=404, detail="Média introuvable")

    payload: dict[str, str | int] = {
        "media_id": media.id,
        "name": media.name,
        "kind": media.kind.value,
    }
    if duration is not None:
        try:
            payload["duration_seconds"] = int(duration)
        except (TypeError, ValueError):
            raise HTTPException(status_code=422, detail="duration_seconds invalide") from None

    # Annule les shows en attente précédents pour ce device.
    for stale in db.scalars(
        select(Command).where(
            Command.device_id == device.id,
            Command.type == CommandType.SHOW,
            Command.status == "pending",
        )
    ):
        stale.status = CommandStatus.FAILED  # type: ignore[assignment, name-defined]
        stale.error = "Remplacé par un trigger"

    cmd = Command(
        device_id=device.id,
        type=CommandType.SHOW,
        payload=json.dumps(payload),
    )
    db.add(cmd)
    db.commit()
    db.refresh(cmd)
    return {"command_id": cmd.id, "device_id": device.id, "media_id": media.id}


@router.post("/{device_id}/playlist")
async def trigger_playlist(
    device_id: str,
    request: Request,
    db: Session = Depends(get_db),
) -> dict:
    """Déclenche la diffusion d'une playlist (le premier média prêt).

    Identique à `trigger_show` mais cible une playlist : le premier média
    prêt de la playlist est affiché immédiatement sur l'écran.
    """
    settings = request.app.state.settings
    if not settings.trigger_secret:
        raise HTTPException(status_code=404, detail="Trigger non configuré")
    if request.headers.get("X-Trigger-Secret", "") != settings.trigger_secret:
        raise HTTPException(status_code=403, detail="Secret invalide")

    body = await request.json()
    playlist_id = body.get("playlist_id")
    if not playlist_id:
        raise HTTPException(status_code=422, detail="playlist_id requis")

    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Appareil introuvable")
    if device.status != DeviceStatus.APPROVED:
        raise HTTPException(status_code=409, detail="Appareil indisponible")

    playlist = db.get(Playlist, playlist_id)
    if playlist is None or playlist.org_id != device.org_id:
        raise HTTPException(status_code=404, detail="Playlist introuvable")
    item = db.scalar(
        select(PlaylistItem).where(PlaylistItem.playlist_id == playlist.id)
        .order_by(PlaylistItem.position)
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Playlist vide")
    media = db.get(Media, item.media_id)
    if media is None or media.status != "ready":
        raise HTTPException(status_code=409, detail="Premier média non prêt")

    payload: dict[str, str | int] = {
        "media_id": media.id,
        "name": media.name,
        "kind": media.kind.value,
    }
    if item.duration_seconds is not None:
        payload["duration_seconds"] = item.duration_seconds

    for stale in db.scalars(
        select(Command).where(
            Command.device_id == device.id,
            Command.type == CommandType.SHOW,
            Command.status == "pending",
        )
    ):
        stale.status = CommandStatus.FAILED  # type: ignore[assignment, name-defined]
        stale.error = "Remplacé par un trigger"

    cmd = Command(device_id=device.id, type=CommandType.SHOW, payload=json.dumps(payload))
    db.add(cmd)
    db.commit()
    db.refresh(cmd)
    return {"command_id": cmd.id, "device_id": device.id, "media_id": media.id}
