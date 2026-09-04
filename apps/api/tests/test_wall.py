"""Mur VNC, heartbeat persisté et Raspberry d'aperçu admin."""

from __future__ import annotations

import io

from elyon_api.models import Media
from elyon_api.services.media_processing import process_media
from elyon_api.services.storage import LocalStorage
from tests.conftest import (
    auth_json,
    bootstrap_superadmin,
    create_org,
    login,
    login_as_org_admin,
)


def png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 36), (20, 80, 160)).save(buf, "PNG")
    return buf.getvalue()


def _ready_playlist(client, settings, db_session_factory, site_id: str) -> str:
    playlist = auth_json(client, "POST", "/api/playlists", json={"name": "Mur"}).json()
    media = auth_json(
        client,
        "POST",
        "/api/media",
        params={"name": "Spot mur"},
        files={"file": ("spot.png", png_bytes(), "image/png")},
    ).json()
    with db_session_factory() as session:
        stored = session.get(Media, media["id"])
        process_media(stored, settings, LocalStorage(settings.media_storage_root))
        session.commit()
    auth_json(
        client,
        "POST",
        f"/api/playlists/{playlist['id']}/items",
        json={"media_id": media["id"], "duration_seconds": 8},
    )
    auth_json(
        client,
        "POST",
        "/api/schedules",
        json={
            "site_id": site_id,
            "playlist_id": playlist["id"],
            "name": "Brouillon",
            "start_at": "2020-01-01T00:00:00Z",
            "end_at": "2099-01-01T00:00:00Z",
            "priority": 0,
        },
    )
    return media["id"]


def _enroll(client, site_id: str, serial: str, name: str) -> dict:
    token = auth_json(client, "POST", "/api/enroll/tokens", params={"site_id": site_id}).json()
    enrolled = client.post(
        "/api/enroll/request",
        json={"serial": serial, "name": name, "site_code": token["code"]},
    )
    assert enrolled.status_code == 201, enrolled.text
    data = enrolled.json()
    auth_json(client, "POST", f"/api/devices/{data['device_id']}/approve")
    return data


def test_heartbeat_persists_now_playing_and_wall(client, settings, db_session_factory):
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "WallCo")
    login_as_org_admin(client, org, "wall@org.test")
    site = auth_json(client, "POST", "/api/sites", json={"name": "Hall"}).json()
    media_id = _ready_playlist(client, settings, db_session_factory, site["id"])
    device = _enroll(client, site["id"], "emu-rpi-1", "Pi 1")
    auth_json(
        client,
        "POST",
        f"/api/sites/{site['id']}/screens",
        json={"name": "Écran 1", "device_id": device["device_id"]},
    )

    hb = client.post(
        f"/api/devices/{device['device_id']}/heartbeat",
        headers={"Authorization": f"Bearer {device['token']}"},
        json={"state": "playing", "current_media_id": media_id},
    )
    assert hb.status_code == 200, hb.text

    listed = client.get("/api/devices").json()
    row = next(d for d in listed if d["id"] == device["device_id"])
    assert row["player_state"] == "playing"
    assert row["current_media_id"] == media_id
    assert row["is_preview"] is False

    wall = client.get("/api/admin/wall").json()
    frame = next(f for f in wall if f["device_id"] == device["device_id"])
    assert frame["player_state"] == "playing"
    assert frame["current_media_name"] == "Spot mur"
    assert frame["current_media_kind"] == "image"

    preview = client.get(f"/api/media/{media_id}/preview-file")
    assert preview.status_code == 200
    assert preview.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_preview_device_gets_live_manifest_without_publish(
    client, settings, db_session_factory
):
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "PrevCo")
    login_as_org_admin(client, org, "prev@org.test")
    site = auth_json(client, "POST", "/api/sites", json={"name": "Lab"}).json()
    _ready_playlist(client, settings, db_session_factory, site["id"])

    prod = _enroll(client, site["id"], "emu-rpi-1", "Pi prod")
    prev = _enroll(client, site["id"], "emu-rpi-preview", "Aperçu administrateur")
    auth_json(
        client,
        "POST",
        f"/api/sites/{site['id']}/screens",
        json={"name": "Écran prod", "device_id": prod["device_id"]},
    )
    auth_json(
        client,
        "POST",
        f"/api/sites/{site['id']}/screens",
        json={"name": "Écran aperçu", "device_id": prev["device_id"]},
    )
    patched = auth_json(
        client, "PATCH", f"/api/devices/{prev['device_id']}", json={"is_preview": True}
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["is_preview"] is True

    missing = client.get(
        f"/api/devices/{prod['device_id']}/manifest",
        headers={"Authorization": f"Bearer {prod['token']}"},
    )
    assert missing.status_code == 404

    live = client.get(
        f"/api/devices/{prev['device_id']}/manifest",
        headers={"Authorization": f"Bearer {prev['token']}"},
    )
    assert live.status_code == 200, live.text
    payload = live.json()
    assert payload["version"] >= 1
    assert payload["signature"]
    assert "Spot mur" in payload["payload"]
    assert '"preview":true' in payload["payload"]
    live2 = client.get(
        f"/api/devices/{prev['device_id']}/manifest",
        headers={"Authorization": f"Bearer {prev['token']}"},
    )
    assert live2.json()["version"] == payload["version"]

    hb = client.post(
        f"/api/devices/{prev['device_id']}/heartbeat",
        headers={"Authorization": f"Bearer {prev['token']}"},
        json={"state": "idle"},
    )
    assert hb.json()["heartbeat_interval_seconds"] == 5
