"""Corbeille des médias : purge automatique après 30 jours."""

from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from elyon_api.models import Media
from elyon_api.services.storage import build_storage

TRASH_RETENTION_DAYS = 30


def purge_expired_trash(factory: sessionmaker, settings) -> int:
    """Supprime définitivement les médias corbeillés depuis plus de 30 jours."""
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=TRASH_RETENTION_DAYS)
    storage = build_storage(settings)
    purged = 0
    with factory() as db:
        expired = db.scalars(
            select(Media).where(Media.deleted_at.is_not(None), Media.deleted_at < cutoff)
        ).all()
        for media in expired:
            storage.delete(media.storage_path)
            if media.pages_json:
                import json

                try:
                    for rel in json.loads(media.pages_json):
                        storage.delete(rel)
                except (ValueError, TypeError):
                    pass
            db.delete(media)
            purged += 1
        if purged:
            db.commit()
    return purged
