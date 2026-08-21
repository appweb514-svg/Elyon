from __future__ import annotations

import datetime as dt
import io
import json

from PIL import Image

from elyon_api.models import Media
from elyon_api.services.media_processing import process_media
from elyon_api.services.signing import (
    load_or_create_signing_key,
    public_key_pem,
    sign_json,
    verify_signature,
)
from elyon_api.services.storage import LocalStorage
from tests.conftest import (
    auth_json,
    bootstrap_superadmin,
    create_org,
    login,
    login_as_org_admin,
)


def png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def setup_device(client, settings, db_session_factory) -> dict:
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "SignCo")
    login_as_org_admin(client, org, "sign@org.test")
    site = auth_json(client, "POST", "/api/sites", json={"name": "Site 1"}).json()
    playlist = auth_json(client, "POST", "/api/playlists", json={"name": "PL"}).json()
    media = client.post(
        "/api/media",
        files={"file": ("a.png", png_bytes(), "image/png")},
        headers={"X-CSRF-Token": client.cookies.get("elyon_csrf", "")},
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
    now = dt.datetime.now(dt.UTC)
    auth_json(
        client,
        "POST",
        "/api/schedules",
        json={
            "site_id": site["id"],
            "playlist_id": playlist["id"],
            "name": "Toute la journée",
            "start_at": (now - dt.timedelta(hours=1)).isoformat(),
            "end_at": (now + dt.timedelta(hours=1)).isoformat(),
        },
    )
    token = auth_json(client, "POST", "/api/enroll/tokens", params={"site_id": site["id"]}).json()
    enroll = client.post(
        "/api/enroll/request",
        json={"serial": "RPI-S1", "name": "P", "site_code": token["code"]},
    ).json()
    device_id = enroll["device_id"]
    auth_json(client, "POST", f"/api/devices/{device_id}/approve")
    auth_json(
        client,
        "POST",
        f"/api/sites/{site['id']}/screens",
        json={"name": "Écran", "device_id": device_id},
    )
    return {"device_id": device_id, "token": enroll["token"], "media": media}


def test_signature_roundtrip(settings):
    key = load_or_create_signing_key(settings)
    payload, signature = sign_json({"a": 1, "b": [2, 3]}, key)
    assert verify_signature(payload, signature, public_key_pem(key))
    assert not verify_signature(payload + " ", signature, public_key_pem(key))
    assert not verify_signature(payload, "AAAA", public_key_pem(key))


def test_signature_canonical_order(settings):
    key = load_or_create_signing_key(settings)
    p1, s1 = sign_json({"b": 1, "a": 2}, key)
    p2, s2 = sign_json({"a": 2, "b": 1}, key)
    assert p1 == p2
    assert s1 == s2


def test_publish_and_fetch(client, settings, db_session_factory):
    env = setup_device(client, settings, db_session_factory)
    pub = auth_json(client, "POST", f"/api/devices/{env['device_id']}/publish")
    assert pub.status_code == 200, pub.text
    manifest = pub.json()
    assert manifest["version"] == 1

    fetched = client.get(
        f"/api/devices/{env['device_id']}/manifest",
        headers={"Authorization": f"Bearer {env['token']}"},
    )
    assert fetched.status_code == 200
    body = fetched.json()
    payload = json.loads(body["payload"])
    assert payload["device_id"] == env["device_id"]
    assert len(payload["blocks"]) == 1
    assert len(payload["blocks"][0]["entries"]) == 1
    assert payload["media"][0]["media_id"] == env["media"]["id"]
    assert payload["media"][0]["url"].endswith(f"/api/media/{env['media']['id']}/file")
    assert body["signature"]

    repub = auth_json(client, "POST", f"/api/devices/{env['device_id']}/publish")
    assert repub.json()["version"] == 2


def test_publish_requires_approved_device(client):
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "SignCo2")
    login_as_org_admin(client, org, "sign2@org.test")
    site = auth_json(client, "POST", "/api/sites", json={"name": "Site 1"}).json()
    token = auth_json(client, "POST", "/api/enroll/tokens", params={"site_id": site["id"]}).json()
    enroll = client.post(
        "/api/enroll/request",
        json={"serial": "RPI-S2", "name": "P", "site_code": token["code"]},
    ).json()
    fetched = client.get(
        f"/api/devices/{enroll['device_id']}/manifest",
        headers={"Authorization": f"Bearer {enroll['token']}"},
    )
    assert fetched.status_code == 403