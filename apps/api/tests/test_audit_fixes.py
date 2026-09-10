"""Tests de non-régression des corrections de l'audit.

Couvre : limitation de débit du login, déduplication du proof-of-play,
garde SSRF des flux RSS, isolation du stockage local, permissions
devices/enrôlement et bornage des requêtes HTTP Range.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from elyon_api.routers import auth as auth_router
from elyon_api.services.storage import LocalStorage, safe_storage_path
from elyon_api.services.widget_feed import _assert_public_feed_url, fetch_rss
from tests.conftest import (
    auth_json,
    bootstrap_superadmin,
    create_org,
    login,
    login_as_org_admin,
)


def test_login_rate_limit_only_counts_failures(client: TestClient):
    """Les connexions réussies ne doivent jamais déclencher le 429."""
    bootstrap_superadmin(client)
    auth_router._login_failures.clear()
    try:
        for _ in range(20):
            response = client.post(
                "/api/auth/login",
                json={"email": "admin@elyon.local", "password": "motdepasse-long"},
            )
            assert response.status_code == 200, response.text
    finally:
        auth_router._login_failures.clear()


def test_login_rate_limit_blocks_repeated_failures(client: TestClient, settings):
    bootstrap_superadmin(client)
    auth_router._login_failures.clear()
    try:
        for _ in range(settings.max_login_attempts_per_minute):
            response = client.post(
                "/api/auth/login",
                json={"email": "admin@elyon.local", "password": "mauvais-mot-de-passe"},
            )
            assert response.status_code == 401
        blocked = client.post(
            "/api/auth/login",
            json={"email": "admin@elyon.local", "password": "motdepasse-long"},
        )
        assert blocked.status_code == 429
    finally:
        auth_router._login_failures.clear()


def test_playback_events_are_deduplicated(client: TestClient, db_session_factory):
    from elyon_api.models import PlaybackEvent

    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "AuditPlay")
    login_as_org_admin(client, org, "play@org.test")
    site = auth_json(client, "POST", "/api/sites", json={"name": "SitePlay"}).json()
    token = auth_json(
        client, "POST", "/api/enroll/tokens", params={"site_id": site["id"]}
    ).json()
    device = client.post(
        "/api/enroll/request",
        json={"serial": "SER-PLAY-1", "name": "DevPlay", "site_code": token["code"]},
    ).json()
    auth_json(client, "POST", f"/api/devices/{device['device_id']}/approve")
    headers = {"Authorization": f"Bearer {device['token']}"}
    url = f"/api/devices/{device['device_id']}/heartbeat"

    for _ in range(3):
        client.post(url, headers=headers, json={"state": "playing", "current_media_id": "m1"})
    with db_session_factory() as session:
        events = session.query(PlaybackEvent).all()
        assert len(events) == 1
        assert events[0].state == "playing"

    # Changement de média : fin de l'ancien + début du nouveau.
    client.post(url, headers=headers, json={"state": "playing", "current_media_id": "m2"})
    with db_session_factory() as session:
        states = [
            (event.media_id, event.state)
            for event in session.query(PlaybackEvent).order_by(PlaybackEvent.recorded_at).all()
        ]
    assert ("m1", "end") in states
    assert ("m2", "playing") in states

    # Arrêt : un seul événement de fin supplémentaire (total 4).
    client.post(url, headers=headers, json={"state": "idle", "current_media_id": None})
    with db_session_factory() as session:
        assert session.query(PlaybackEvent).count() == 4
        event = session.query(PlaybackEvent).order_by(PlaybackEvent.recorded_at.desc()).first()
        assert event.media_id == "m2"
        assert event.state == "end"


def test_rss_feed_blocks_ssrf_targets():
    for url in (
        "file:///etc/passwd",
        "http://127.0.0.1/feed.xml",
        "http://localhost/feed.xml",
        "http://169.254.169.254/latest/meta-data/",
        "http://[::1]/feed.xml",
        "ftp://example.com/feed.xml",
    ):
        with pytest.raises(HTTPException) as exc:
            fetch_rss(url)
        assert exc.value.status_code in (400, 502)


def test_rss_feed_accepts_public_ip_literal():
    # Adresse publique littérale : aucune résolution DNS nécessaire.
    _assert_public_feed_url("http://93.184.216.34/feed.xml")


def test_local_storage_rejects_prefix_confusion(tmp_path):
    storage = LocalStorage(tmp_path / "media")
    with pytest.raises(ValueError):
        storage._abs("../media-evil/secret.txt")
    with pytest.raises(ValueError):
        storage._abs("../../etc/passwd")
    assert safe_storage_path("originals/ok/file") == "originals/ok/file"


def _viewer_operator_setup(client: TestClient) -> tuple[dict, dict]:
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "RbacFix")
    login_as_org_admin(client, org, "rbacfix@org.test")
    site = auth_json(client, "POST", "/api/sites", json={"name": "SiteRbac"}).json()
    token = auth_json(
        client, "POST", "/api/enroll/tokens", params={"site_id": site["id"]}
    ).json()
    device = client.post(
        "/api/enroll/request",
        json={"serial": "SER-RBAC-1", "name": "DevRbac", "site_code": token["code"]},
    ).json()
    auth_json(client, "POST", f"/api/devices/{device['device_id']}/approve")
    login(client)  # superadmin
    users = {}
    for role in ("viewer", "operator"):
        email = f"{role}-{role}@rbac.test"
        created = auth_json(
            client,
            "POST",
            "/api/users",
            json={
                "email": email,
                "password": "motdepasse-long",
                "full_name": role,
                "role": role,
                "org_id": org["id"],
                "site_id": site["id"],
            },
        )
        assert created.status_code == 201, created.text
        users[role] = email
    return device, users


def test_viewer_and_operator_cannot_mutate_devices(client: TestClient):
    device, users = _viewer_operator_setup(client)
    for role, email in users.items():
        login(client, email)
        # Lecture autorisée.
        assert client.get(f"/api/devices/{device['device_id']}").status_code == 200
        # Écriture interdite.
        patch = auth_json(
            client,
            "PATCH",
            f"/api/devices/{device['device_id']}",
            json={"name": "Renommé"},
        )
        assert patch.status_code == 403, f"{role} PATCH device: {patch.text}"
        enroll = auth_json(
            client,
            "POST",
            "/api/enroll/tokens",
            params={"site_id": device["device_id"]},
        )
        assert enroll.status_code in (403, 404), f"{role} enroll token: {enroll.text}"


def test_media_range_request_is_clamped(client: TestClient):
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "RangeOrg")
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\xcf\xc0"
        b"\x00\x00\x00\x03\x00\x01\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    upload = auth_json(
        client,
        "POST",
        "/api/media",
        data={"org_id": org["id"]},
        files={"file": ("p.png", png, "image/png")},
    )
    assert upload.status_code == 201, upload.text
    media_id = upload.json()["id"]
    response = client.get(
        f"/api/media/{media_id}/preview-file",
        headers={"Range": "bytes=0-999999"},
    )
    assert response.status_code == 206
    content_range = response.headers["content-range"]
    _, _, total = content_range.partition("/")
    start, _, end = content_range.split(" ")[1].partition("/")[0].partition("-")
    assert int(start) == 0
    assert int(end) == int(total) - 1


def test_wall_live_requires_session(client: TestClient):
    """Le flux MJPEG ne doit pas être exposé sans authentification."""
    response = client.get("/api/admin/wall/00000000000000000000000000000000/live")
    assert response.status_code == 401


# --- Pagination, traitement média multi-backend, auto-enchaînement -------


class _MemoryStorage:
    """Backend en mémoire : prouve que le traitement ne dépend pas du disque."""

    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def open_read(self, path: str):
        import io

        return io.BytesIO(self.files[path])

    def iter_read(
        self,
        path: str,
        start: int = 0,
        end: int | None = None,
        chunk_size: int = 1 << 20,
    ):
        data = self.files[path]
        if end is None:
            end = len(data) - 1
        yield data[start : end + 1]

    def write(self, path: str, data) -> None:
        self.files[path] = data.read()

    def append(self, path: str, data: bytes) -> None:
        self.files[path] = self.files.get(path, b"") + data

    def size(self, path: str) -> int:
        return len(self.files[path])

    def delete(self, path: str) -> None:
        self.files.pop(path, None)

    def exists(self, path: str) -> bool:
        return path in self.files

    def list(self, prefix: str) -> list[str]:
        return [key for key in self.files if key.startswith(prefix)]

    def move(self, src: str, dst: str) -> None:
        self.files[dst] = self.files.pop(src)


def _tiny_png() -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (4, 4), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def _org_setup(client: TestClient):
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "RemainingCo")
    login_as_org_admin(client, org, "remaining@org.test")
    return org


def _upload_png(client: TestClient, name: str = "p.png") -> dict:
    response = auth_json(
        client,
        "POST",
        "/api/media",
        files={"file": (name, _tiny_png(), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _approved_device(client: TestClient, serial: str) -> dict:
    site = auth_json(client, "POST", "/api/sites", json={"name": f"Site-{serial}"}).json()
    token = auth_json(
        client, "POST", "/api/enroll/tokens", params={"site_id": site["id"]}
    ).json()
    device = client.post(
        "/api/enroll/request",
        json={"serial": serial, "name": "Dev", "site_code": token["code"]},
    ).json()
    auth_json(client, "POST", f"/api/devices/{device['device_id']}/approve")
    return device


def test_media_pagination_and_total_header(client: TestClient):
    _org_setup(client)
    for index in range(3):
        _upload_png(client, f"p{index}.png")

    page = client.get("/api/media?limit=2&offset=0")
    assert page.status_code == 200
    assert len(page.json()) == 2
    assert page.headers["x-total-count"] == "3"

    page2 = client.get("/api/media?limit=2&offset=2")
    assert page2.status_code == 200
    assert len(page2.json()) == 1


def test_devices_pagination_and_total_header(client: TestClient):
    _org_setup(client)
    _approved_device(client, "SER-PAGE-1")
    _approved_device(client, "SER-PAGE-2")

    page = client.get("/api/devices?limit=1&offset=0")
    assert page.status_code == 200
    assert len(page.json()) == 1
    assert int(page.headers["x-total-count"]) >= 2


def test_process_media_with_nonlocal_storage(client: TestClient, settings, db_session_factory):
    """Le traitement média ne doit pas exiger un disque local (compatible S3)."""
    import json

    from elyon_api.models import Media, MediaStatus
    from elyon_api.services.media_processing import process_media

    _org_setup(client)
    media_id = _upload_png(client, "conv.png")["id"]
    storage = _MemoryStorage()
    with db_session_factory() as session:
        row = session.get(Media, media_id)
        storage.files[row.storage_path] = _tiny_png()
        process_media(row, settings, storage)
        assert row.status == MediaStatus.READY
        pages = json.loads(row.pages_json)
        assert pages[0] == row.storage_path
        assert pages[1] == f"thumbs/{row.id}.jpg"
        assert f"thumbs/{row.id}.jpg" in storage.files


def test_queue_auto_advance_persists_state_in_db(client: TestClient, db_session_factory):
    """L'auto-enchaînement doit fonctionner entre deux répliques (état en base)."""
    import datetime as dt

    from elyon_api.models import Device

    _org_setup(client)
    device = _approved_device(client, "SER-QUEUE-1")
    headers = {"Authorization": f"Bearer {device['token']}"}
    media1 = _upload_png(client, "q1.png")["id"]
    media2 = _upload_png(client, "q2.png")["id"]
    for media_id in (media1, media2):
        queued = auth_json(
            client,
            "POST",
            f"/api/devices/{device['device_id']}/queue",
            json={"media_id": media_id},
        )
        assert queued.status_code == 201, queued.text
    played = auth_json(
        client,
        "POST",
        f"/api/devices/{device['device_id']}/queue/play",
        json={"media_id": media1},
    )
    assert played.status_code == 201, played.text

    heartbeat = client.post(
        f"/api/devices/{device['device_id']}/heartbeat",
        headers=headers,
        json={"state": "playing", "current_media_id": media1},
    )
    assert heartbeat.status_code == 200
    with db_session_factory() as session:
        row = session.get(Device, device["device_id"])
        assert row.queue_started_media_id == media1
        assert row.queue_started_at is not None
        # Simule 60 s de lecture (au-delà du seuil image de 10 s).
        row.queue_started_at = row.queue_started_at - dt.timedelta(seconds=60)
        session.commit()

    heartbeat = client.post(
        f"/api/devices/{device['device_id']}/heartbeat",
        headers=headers,
        json={"state": "playing", "current_media_id": media1},
    )
    assert heartbeat.status_code == 200
    with db_session_factory() as session:
        row = session.get(Device, device["device_id"])
        assert row.current_media_id == media2
        assert row.queue_started_media_id == media2
    commands = client.get(
        f"/api/devices/{device['device_id']}/commands", headers=headers
    ).json()
    assert any(
        command["type"] == "show" and media2 in (command["payload"] or "")
        for command in commands
    )


def test_auto_advance_allowed_respects_stop_freeze():
    import datetime as dt

    from elyon_api.models import Device
    from elyon_api.services.playback_state import auto_advance_allowed, mark_queue_stopped

    device = Device(org_id="o", name="n", serial="s")
    assert auto_advance_allowed(device)
    mark_queue_stopped(device)
    assert device.queue_started_media_id is None
    assert device.queue_stop_until is not None
    assert not auto_advance_allowed(device)
    device.queue_stop_until = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=1)
    assert auto_advance_allowed(device)
