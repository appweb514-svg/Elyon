from __future__ import annotations

import datetime as dt
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from elyon_api.config import Settings
from elyon_api.models import Device, Manifest, Media, MediaStatus, PlaylistItem
from elyon_api.services.schedule import active_schedules
from elyon_api.services.signing import load_or_create_signing_key, sign_json


def build_manifest_payload(
    db: Session, device: Device, settings: Settings, at: dt.datetime
) -> dict:
    screen = device.screen
    site = device.site
    blocks = []
    media_by_id: dict[str, Media] = {}
    if screen is not None and site is not None:
        for schedule in active_schedules(db, site.id, at):
            items = db.scalars(
                select(PlaylistItem)
                .where(PlaylistItem.playlist_id == schedule.playlist_id)
                .order_by(PlaylistItem.position)
            ).all()
            entries = []
            for item in items:
                media = db.get(Media, item.media_id)
                if media is None or media.status != MediaStatus.READY:
                    continue
                media_by_id[media.id] = media
                entries.append(
                    {
                        "media_id": media.id,
                        "name": media.name,
                        "kind": media.kind.value,
                        "duration_seconds": item.duration_seconds,
                    }
                )
            if entries:
                blocks.append(
                    {
                        "schedule_id": schedule.id,
                        "schedule_name": schedule.name,
                        "priority": schedule.priority,
                        "playlist_id": schedule.playlist_id,
                        "entries": entries,
                    }
                )
    return {
        "device_id": device.id,
        "screen_id": screen.id if screen else None,
        "site_id": site.id if site else None,
        "published_at": at.isoformat(),
        "media": [
            {
                "media_id": m.id,
                "name": m.name,
                "kind": m.kind.value,
                "url": f"{settings.public_base_url.rstrip('/')}/api/media/{m.id}/file",
                "sha256": m.sha256,
                "size_bytes": m.size_bytes,
                "pages": json.loads(m.pages_json) if m.pages_json else None,
            }
            for m in media_by_id.values()
        ],
        "blocks": blocks,
    }


def publish_manifest(db: Session, device: Device, settings: Settings) -> Manifest:
    at = dt.datetime.now(dt.UTC)
    payload = build_manifest_payload(db, device, settings, at)
    private_key = load_or_create_signing_key(settings)
    payload_json, signature = sign_json(payload, private_key)
    next_version = (db.scalar(
        select(func.max(Manifest.version)).where(Manifest.device_id == device.id)
    ) or 0) + 1
    manifest = Manifest(
        device_id=device.id,
        screen_id=payload["screen_id"],
        version=next_version,
        payload=payload_json,
        signature=signature,
        published_at=at,
    )
    db.add(manifest)
    db.commit()
    db.refresh(manifest)
    return manifest


def latest_manifest(db: Session, device_id: str) -> Manifest | None:
    return db.scalar(
        select(Manifest)
        .where(Manifest.device_id == device_id)
        .order_by(Manifest.version.desc())
        .limit(1)
    )