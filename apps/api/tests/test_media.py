from __future__ import annotations

import io

from tests.conftest import (
    auth_json,
    bootstrap_superadmin,
    create_org,
    login,
    login_as_org_admin,
)


def setup(client) -> dict:
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "MediaCo")
    login_as_org_admin(client, org, "media@org.test")
    return org


def upload(client, content: bytes, filename: str, content_type: str, name: str | None = None):
    return client.post(
        "/api/media",
        files={"file": (filename, io.BytesIO(content), content_type)},
        params={"name": name} if name else None,
        headers={"X-CSRF-Token": client.cookies.get("elyon_csrf", "")},
    )


def test_upload_image(client):
    setup(client)
    resp = upload(client, b"\x89PNG\r\n\x1a\nfake-png-data", "logo.png", "image/png", "Logo")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["kind"] == "image"
    assert body["sha256"]
    assert body["size_bytes"] == len(b"\x89PNG\r\n\x1a\nfake-png-data")
    listing = client.get("/api/media")
    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_upload_invalid_type(client):
    setup(client)
    resp = upload(client, b"some text", "notes.txt", "text/plain")
    assert resp.status_code == 400


def test_upload_empty(client):
    setup(client)
    resp = upload(client, b"", "vide.png", "image/png")
    assert resp.status_code == 400


def test_upload_too_big(client, settings):
    setup(client)
    big = b"x" * (settings.max_media_bytes + 1024)
    resp = upload(client, big, "big.mp4", "video/mp4")
    assert resp.status_code == 413


def test_upload_quota(client, settings, db_session_factory):
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "Petite")
    settings.org_quota_bytes = 100
    login_as_org_admin(client, org, "petite@org.test")
    too_much = b"y" * 150
    resp = upload(client, too_much, "quota.png", "image/png")
    assert resp.status_code == 413


def test_media_file_with_device_auth(client):
    setup(client)
    site = auth_json(client, "POST", "/api/sites", json={"name": "Site 1"}).json()
    token = auth_json(client, "POST", "/api/enroll/tokens", params={"site_id": site["id"]}).json()
    enroll = client.post(
        "/api/enroll/request",
        json={"serial": "RPI-M1", "name": "P", "site_code": token["code"]},
    ).json()
    device_id = enroll["device_id"]
    auth_json(client, "POST", f"/api/devices/{device_id}/approve")

    resp = upload(client, b"\x89PNG\r\n\x1a\ndata-image", "pic.png", "image/png", "Pic")
    media = resp.json()
    headers = {"Authorization": f"Bearer {enroll['token']}"}

    download = client.get(f"/api/media/{media['id']}/file", headers=headers)
    assert download.status_code == 200
    assert download.content == b"\x89PNG\r\n\x1a\ndata-image"


def test_media_file_range(client):
    setup(client)
    site = auth_json(client, "POST", "/api/sites", json={"name": "Site 1"}).json()
    token = auth_json(client, "POST", "/api/enroll/tokens", params={"site_id": site["id"]}).json()
    enroll = client.post(
        "/api/enroll/request",
        json={"serial": "RPI-M2", "name": "P", "site_code": token["code"]},
    ).json()
    auth_json(client, "POST", f"/api/devices/{enroll['device_id']}/approve")

    content = b"0123456789abcdef"
    media = upload(client, content, "range.bin", "video/mp4").json()
    headers = {
        "Authorization": f"Bearer {enroll['token']}",
        "Range": "bytes=4-7",
    }
    resp = client.get(f"/api/media/{media['id']}/file", headers=headers)
    assert resp.status_code == 206
    assert resp.content == b"4567"
    assert resp.headers["Content-Range"] == f"bytes 4-7/{len(content)}"


def test_media_file_requires_device_token(client):
    setup(client)
    media = upload(client, b"data", "d.png", "image/png").json()
    resp = client.get(f"/api/media/{media['id']}/file")
    assert resp.status_code == 401


def test_delete_media(client, settings):
    setup(client)
    media = upload(client, b"data", "d.png", "image/png").json()
    settings.media_storage_root / "originals"
    resp = auth_json(client, "DELETE", f"/api/media/{media['id']}")
    assert resp.status_code == 204
    listing = client.get("/api/media")
    assert listing.json() == []