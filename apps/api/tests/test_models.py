from __future__ import annotations

import datetime as dt

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from elyon_api.models import (
    Media,
    Organization,
    Role,
    Schedule,
    Site,
    User,
)


def make_org_and_site(factory) -> tuple:
    with factory() as session:
        org = Organization(name="Test", slug="test", quota_bytes=1000)
        session.add(org)
        session.commit()
        session.refresh(org)
        site = Site(org_id=org.id, name="Site A")
        session.add(site)
        session.commit()
        session.refresh(site)
        return org, site


def test_unique_org_name(db_session_factory):
    with db_session_factory() as session:
        session.add(Organization(name="X", slug="x"))
        session.commit()
        session.add(Organization(name="X", slug="y"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_unique_email(db_session_factory):
    with db_session_factory() as session:
        session.add(User(email="a@b.c", password_hash="h", full_name="A", role=Role.VIEWER))
        session.commit()
        session.add(User(email="a@b.c", password_hash="h", full_name="B", role=Role.VIEWER))
        with pytest.raises(IntegrityError):
            session.commit()


def test_site_name_unique_per_org(db_session_factory):
    org, _ = make_org_and_site(db_session_factory)
    with db_session_factory() as session:
        session.add(Site(org_id=org.id, name="Site A"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_schedule_window_check(db_session_factory):
    org, site = make_org_and_site(db_session_factory)
    with db_session_factory() as session:
        session.add(
            Schedule(
                org_id=org.id,
                site_id=site.id,
                playlist_id="x",
                name="Invalide",
                start_at=dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
                end_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_device_serial_unique(db_session_factory):
    org, _ = make_org_and_site(db_session_factory)
    with db_session_factory() as session:
        from elyon_api.models import Device

        session.add(Device(org_id=org.id, name="P1", serial="S1"))
        session.commit()
        session.add(Device(org_id=org.id, name="P2", serial="S1"))
        with pytest.raises(IntegrityError):
            session.commit()


def test_schedule_foreign_key_restrict(db_session_factory):
    org, site = make_org_and_site(db_session_factory)
    with db_session_factory() as session:
        session.add(
            Schedule(
                org_id=org.id,
                site_id=site.id,
                playlist_id="missing",
                name="Orphelin",
                start_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
                end_at=dt.datetime(2026, 1, 2, tzinfo=dt.UTC),
            )
        )
        with pytest.raises(IntegrityError):
            session.commit()


def test_media_quota_and_sha256(db_session_factory):
    org, _ = make_org_and_site(db_session_factory)
    with db_session_factory() as session:
        from elyon_api.models import MediaKind

        session.add(
            Media(
                org_id=org.id,
                name="M",
                original_filename="m.png",
                kind=MediaKind.IMAGE,
                mime_type="image/png",
                size_bytes=10,
                storage_path="originals/x",
            )
        )
        session.commit()
        stored = session.scalar(select(Media))
        assert stored.sha256 is None
        assert stored.size_bytes == 10


def test_playlist_item_position_unique(db_session_factory):
    org, _ = make_org_and_site(db_session_factory)
    with db_session_factory() as session:
        from elyon_api.models import MediaKind, Playlist, PlaylistItem

        playlist = Playlist(org_id=org.id, name="PL")
        session.add(playlist)
        session.flush()
        media = Media(
            org_id=org.id,
            name="M",
            original_filename="m.png",
            kind=MediaKind.IMAGE,
            mime_type="image/png",
            size_bytes=1,
            storage_path="o/x",
        )
        session.add(media)
        session.flush()
        session.add(PlaylistItem(playlist_id=playlist.id, media_id=media.id, position=1))
        session.commit()
        session.add(PlaylistItem(playlist_id=playlist.id, media_id=media.id, position=1))
        with pytest.raises(IntegrityError):
            session.commit()


def test_screen_device_unique(db_session_factory):
    org, site = make_org_and_site(db_session_factory)
    with db_session_factory() as session:
        from elyon_api.models import Device, Screen

        device = Device(org_id=org.id, name="P", serial="S")
        session.add(device)
        session.flush()
        session.add(Screen(org_id=org.id, site_id=site.id, name="E1", device_id=device.id))
        session.add(Screen(org_id=org.id, site_id=site.id, name="E2", device_id=device.id))
        with pytest.raises(IntegrityError):
            session.commit()