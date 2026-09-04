from __future__ import annotations

import datetime as dt
import io
import json

from PIL import Image

from elyon_api.models import Media
from elyon_api.services.media_processing import process_media
from elyon_api.services.storage import LocalStorage
from tests.conftest import auth_json, bootstrap_superadmin, create_org, login, login_as_org_admin


def png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (32, 32), (10, 90, 160)).save(buf, "PNG")
    return buf.getvalue()


def setup_playlist(client, settings, db_session_factory):
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "RevisionCo")
    login_as_org_admin(client, org, "revision@org.test")
    site = auth_json(client, "POST", "/api/sites", json={"name": "Site"}).json()
    playlist = auth_json(client, "POST", "/api/playlists", json={"name": "Accueil"}).json()
    media = client.post(
        "/api/media",
        files={"file": ("image.png", png_bytes(), "image/png")},
        headers={"X-CSRF-Token": client.cookies.get("elyon_csrf", "")},
    ).json()
    with db_session_factory() as session:
        stored = session.get(Media, media["id"])
        process_media(stored, settings, LocalStorage(settings.media_storage_root))
        session.commit()
    return site, playlist, media


def test_playlist_validation_and_publish(client, settings, db_session_factory):
    _, playlist, media = setup_playlist(client, settings, db_session_factory)
    invalid = client.get(f"/api/playlists/{playlist['id']}/validate")
    assert invalid.status_code == 200
    assert invalid.json()["valid"] is False

    added = auth_json(
        client,
        "POST",
        f"/api/playlists/{playlist['id']}/items",
        json={"media_id": media["id"], "duration_seconds": 5},
    )
    assert added.status_code == 201
    valid = client.get(f"/api/playlists/{playlist['id']}/validate").json()
    assert valid["valid"] is True

    published = auth_json(client, "POST", f"/api/playlists/{playlist['id']}/publish")
    assert published.status_code == 200, published.text
    assert published.json()["version"] == 1
    detail = client.get(f"/api/playlists/{playlist['id']}").json()
    assert detail["published_version"] == 1
    assert detail["draft_changed"] is False


def test_draft_does_not_change_published_manifest(client, settings, db_session_factory):
    site, playlist, media = setup_playlist(client, settings, db_session_factory)
    auth_json(
        client,
        "POST",
        f"/api/playlists/{playlist['id']}/items",
        json={"media_id": media["id"], "duration_seconds": 5},
    )
    auth_json(client, "POST", f"/api/playlists/{playlist['id']}/publish")
    second = client.post(
        "/api/media",
        files={"file": ("second.png", png_bytes(), "image/png")},
        headers={"X-CSRF-Token": client.cookies.get("elyon_csrf", "")},
    ).json()
    with db_session_factory() as session:
        stored = session.get(Media, second["id"])
        process_media(stored, settings, LocalStorage(settings.media_storage_root))
        session.commit()
    auth_json(
        client,
        "POST",
        f"/api/playlists/{playlist['id']}/items",
        json={"media_id": second["id"], "duration_seconds": 7},
    )
    diff = client.get(f"/api/playlists/{playlist['id']}/diff").json()
    assert diff["changed"] is True
    assert second["id"] in diff["added"]

    token = auth_json(client, "POST", "/api/enroll/tokens", params={"site_id": site["id"]}).json()
    enrolled = client.post(
        "/api/enroll/request",
        json={"serial": "REV-RPI", "name": "Revision player", "site_code": token["code"]},
    ).json()
    auth_json(client, "POST", f"/api/devices/{enrolled['device_id']}/approve")
    auth_json(
        client,
        "POST",
        f"/api/sites/{site['id']}/screens",
        json={"name": "Screen", "device_id": enrolled["device_id"]},
    )
    schedule = auth_json(
        client,
        "POST",
        "/api/schedules",
        json={
            "site_id": site["id"],
            "playlist_id": playlist["id"],
            "name": "Permanent",
            "start_at": (dt.datetime.now(dt.UTC) - dt.timedelta(hours=1)).isoformat(),
            "end_at": (dt.datetime.now(dt.UTC) + dt.timedelta(hours=1)).isoformat(),
        },
    )
    assert schedule.status_code == 201
    published_manifest = auth_json(
        client, "POST", f"/api/devices/{enrolled['device_id']}/publish"
    ).json()
    payload = json.loads(published_manifest["payload"])
    assert second["id"] not in json.dumps(payload)


def test_duplicate_playlist_copies_draft(client, settings, db_session_factory):
    _, playlist, media = setup_playlist(client, settings, db_session_factory)
    auth_json(
        client,
        "POST",
        f"/api/playlists/{playlist['id']}/items",
        json={"media_id": media["id"], "duration_seconds": 9},
    )
    duplicate = auth_json(
        client,
        "POST",
        f"/api/playlists/{playlist['id']}/duplicate",
        json={"name": "Accueil copie"},
    )
    assert duplicate.status_code == 201, duplicate.text
    assert duplicate.json()["items"][0]["media_id"] == media["id"]
