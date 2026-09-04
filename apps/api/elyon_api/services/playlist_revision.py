from __future__ import annotations

import json

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from elyon_api.models import Media, MediaStatus, Playlist, PlaylistItem, PlaylistRevision, new_id


class PlaylistValidationError(ValueError):
    def __init__(self, errors: list[str]) -> None:
        super().__init__("; ".join(errors))
        self.errors = errors


def draft_items(playlist: Playlist) -> list[PlaylistItem]:
    return sorted(playlist.items, key=lambda item: item.position)


def snapshot_items(playlist: Playlist) -> list[dict]:
    return [
        {
            "id": item.id,
            "media_id": item.media_id,
            "position": item.position,
            "duration_seconds": item.duration_seconds,
        }
        for item in draft_items(playlist)
    ]


def revision_items(revision: PlaylistRevision) -> list[dict]:
    try:
        value = json.loads(revision.items_json)
    except (TypeError, ValueError):
        return []
    return value if isinstance(value, list) else []


def validate_playlist(db: Session, playlist: Playlist) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    items = draft_items(playlist)
    if not items:
        errors.append("La playlist doit contenir au moins un média")
    positions = [item.position for item in items]
    if positions != list(range(1, len(items) + 1)):
        errors.append("Les positions de la playlist doivent être contiguës")
    total_duration = 0
    for index, item in enumerate(items, start=1):
        media = db.get(Media, item.media_id)
        if media is None or media.org_id != playlist.org_id:
            errors.append(f"Élément {index} : média introuvable")
            continue
        if media.deleted_at is not None:
            errors.append(f"Élément {index} : média supprimé")
        elif media.status != MediaStatus.READY:
            errors.append(f"Élément {index} : média non prêt")
        if item.duration_seconds is not None:
            total_duration += item.duration_seconds
        elif media.duration_ms is not None:
            total_duration += max(1, round(media.duration_ms / 1000))
        elif media.kind.value != "video":
            warnings.append(f"Élément {index} : durée par défaut du player")
    return {
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "item_count": len(items),
        "total_duration_seconds": total_duration,
    }


def ensure_initial_revision(db: Session, playlist: Playlist, *, user_id: str | None = None) -> None:
    if published_revision(db, playlist) is None:
        create_revision(db, playlist, user_id=user_id, validate=False)


def create_revision(
    db: Session,
    playlist: Playlist,
    *,
    user_id: str | None = None,
    status: str = "published",
    validate: bool = True,
) -> PlaylistRevision:
    validation = validate_playlist(db, playlist)
    if validate and status == "published" and not validation["valid"]:
        raise PlaylistValidationError(validation["errors"])
    version = (
        db.scalar(
            select(func.max(PlaylistRevision.version)).where(
                PlaylistRevision.playlist_id == playlist.id
            )
        )
        or 0
    ) + 1
    revision = PlaylistRevision(
        id=new_id(),
        playlist_id=playlist.id,
        version=version,
        status=status,
        items_json=json.dumps(snapshot_items(playlist), separators=(",", ":")),
        created_by=user_id,
    )
    db.add(revision)
    db.flush()
    if status == "published":
        playlist.published_revision_id = revision.id
    return revision


def published_revision(db: Session, playlist: Playlist) -> PlaylistRevision | None:
    if playlist.published_revision_id:
        revision = db.get(PlaylistRevision, playlist.published_revision_id)
        if revision is not None:
            return revision
    return db.scalar(
        select(PlaylistRevision)
        .where(
            PlaylistRevision.playlist_id == playlist.id,
            PlaylistRevision.status == "published",
        )
        .order_by(PlaylistRevision.version.desc())
        .limit(1)
    )


def diff_playlist(db: Session, playlist: Playlist) -> dict:
    published = published_revision(db, playlist)
    before = revision_items(published) if published else []
    after = snapshot_items(playlist)
    before_ids = [item["media_id"] for item in before]
    after_ids = [item["media_id"] for item in after]
    return {
        "published_version": published.version if published else None,
        "draft": after,
        "published": before,
        "added": [media_id for media_id in after_ids if media_id not in before_ids],
        "removed": [media_id for media_id in before_ids if media_id not in after_ids],
        "reordered": before_ids != after_ids and set(before_ids) == set(after_ids),
        "changed": before != after,
    }
