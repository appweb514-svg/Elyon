from __future__ import annotations

import os
from pathlib import Path


def test_migration_idempotent(tmp_path):
    os.environ["ELYON_DATABASE_URL"] = f"sqlite:///{tmp_path / 'mig.db'}"
    os.environ["ELYON_SIGNING_KEY_FILE"] = str(tmp_path / "k.pem")
    os.environ["ELYON_MEDIA_STORAGE_ROOT"] = str(tmp_path / "media")

    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect

    from elyon_api import models as _models  # noqa: F401
    from elyon_api.models import Base  # noqa: F401

    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    cfg.set_main_option(
        "script_location", str(Path(__file__).resolve().parents[1] / "migrations")
    )
    command.upgrade(cfg, "head")
    command.upgrade(cfg, "head")

    engine = create_engine(f"sqlite:///{tmp_path / 'mig.db'}")
    inspector = inspect(engine)
    tables = set(inspector.get_table_names())
    expected = {
        "organizations",
        "users",
        "sites",
        "devices",
        "screens",
        "enrollment_tokens",
        "media",
        "playlists",
        "playlist_items",
        "playlist_revisions",
        "schedules",
        "manifests",
        "audit_logs",
        "events",
        "commands",
        "media_processing_jobs",
    }
    assert expected.issubset(tables)
    device_cols = {c["name"] for c in inspector.get_columns("devices")}
    assert {"player_state", "current_media_id", "is_preview"}.issubset(device_cols)
    playlist_cols = {c["name"] for c in inspector.get_columns("playlists")}
    assert "published_revision_id" in playlist_cols
    del os.environ["ELYON_DATABASE_URL"]
    del os.environ["ELYON_SIGNING_KEY_FILE"]
    del os.environ["ELYON_MEDIA_STORAGE_ROOT"]