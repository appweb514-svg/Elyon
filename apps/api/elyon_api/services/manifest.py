from __future__ import annotations

import datetime as dt
import hashlib
import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from elyon_api.config import Settings
from elyon_api.models import Device, Manifest, Media, MediaKind, MediaStatus, PlaylistItem
from elyon_api.services.schedule import active_schedules
from elyon_api.services.signing import load_or_create_signing_key, sign_json
from elyon_api.services.storage import StorageBackend, build_storage


def _file_digest(storage: StorageBackend, path: str) -> tuple[str, int]:
    """SHA-256 et taille d'un fichier de stockage (pour intégrité côté player)."""
    digest = hashlib.sha256()
    size = 0
    with storage.open_read(path) as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _media_entry(media: Media, storage: StorageBackend, settings: Settings) -> dict:
    base = settings.public_base_url.rstrip("/")
    entry = {
        "media_id": media.id,
        "name": media.name,
        "kind": media.kind.value,
        "url": f"{base}/api/media/{media.id}/file",
        "sha256": media.sha256,
        "size_bytes": media.size_bytes,
        "pages": json.loads(media.pages_json) if media.pages_json else None,
    }
    if media.kind == MediaKind.PDF and media.pages_json:
        page_files = []
        for index, page_path in enumerate(json.loads(media.pages_json)):
            sha, size = _file_digest(storage, page_path)
            page_files.append(
                {
                    "index": index,
                    "url": f"{base}/api/media/{media.id}/pages/{index}/file",
                    "sha256": sha,
                    "size_bytes": size,
                }
            )
        entry["page_files"] = page_files
    return entry


def build_manifest_payload(
    db: Session, device: Device, settings: Settings, at: dt.datetime
) -> dict:
    screen = device.screen
    site = device.site
    blocks = []
    media_by_id: dict[str, Media] = {}
    storage = build_storage(settings)
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
        "media": [_media_entry(m, storage, settings) for m in media_by_id.values()],
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