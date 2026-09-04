"""« Afficher » sur un Raspberry et « Ajouter à la playliste »."""

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


def setup(client) -> dict:
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "ShowCo")
    login_as_org_admin(client, org, "show@org.test")
    site = auth_json(client, "POST", "/api/sites", json={"name": "Hall"}).json()
    token = auth_json(
        client, "POST", "/api/enroll/tokens", params={"site_id": site["id"]}
    ).json()
    enroll = client.post(
        "/api/enroll/request",
        json={"serial": "RPI-SHOW", "name": "Raspberry 1", "site_code": token["code"]},
    ).json()
    auth_json(client, "POST", f"/api/devices/{enroll['device_id']}/approve")
    media = auth_json(
        client,
        "POST",
        "/api/media",
        params={"name": "Spot"},
        files={"file": ("spot.png", png_bytes(), "image/png")},
    ).json()
    return {**enroll, "site": site, "media": media}


def _ready_media(client, settings, db_session_factory, media: dict) -> None:
    with db_session_factory() as session:
        stored = session.get(Media, media["id"])
        process_media(stored, settings, LocalStorage(settings.media_storage_root))
        session.commit()


def test_show_sends_command_to_selected_device(client, settings, db_session_factory):
    env = setup(client)
    _ready_media(client, settings, db_session_factory, env["media"])

    resp = auth_json(
        client,
        "POST",
        f"/api/media/{env['media']['id']}/show",
        json={"device_id": env["device_id"]},
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["device_id"] == env["device_id"]
    assert body["media_id"] == env["media"]["id"]
    assert body["command_id"]

    commands = client.get(
        f"/api/devices/{env['device_id']}/commands",
        headers={"Authorization": f"Bearer {env['token']}"},
    ).json()
    assert len(commands) == 1
    assert commands[0]["type"] == "show"
    import json as _json

    payload = _json.loads(commands[0]["payload"])
    assert payload["media_id"] == env["media"]["id"]
    assert payload["kind"] == "image"


def test_show_with_duration(client, settings, db_session_factory):
    env = setup(client)
    _ready_media(client, settings, db_session_factory, env["media"])

    resp = auth_json(
        client,
        "POST",
        f"/api/media/{env['media']['id']}/show",
        json={"device_id": env["device_id"], "duration_seconds": 25},
    )
    assert resp.status_code == 201, resp.text
    commands = client.get(
        f"/api/devices/{env['device_id']}/commands",
        headers={"Authorization": f"Bearer {env['token']}"},
    ).json()
    import json as _json

    payload = _json.loads(commands[0]["payload"])
    assert payload["duration_seconds"] == 25


def test_show_requires_own_media(client, settings, db_session_factory):
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "Isolation")
    login_as_org_admin(client, org, "owner@iso.test")
    site = auth_json(client, "POST", "/api/sites", json={"name": "Hall iso"}).json()
    token = auth_json(client, "POST", "/api/enroll/tokens", params={"site_id": site["id"]}).json()
    enroll = client.post(
        "/api/enroll/request",
        json={"serial": "RPI-ISO", "name": "Pi iso", "site_code": token["code"]},
    ).json()
    auth_json(client, "POST", f"/api/devices/{enroll['device_id']}/approve")
    media = auth_json(
        client,
        "POST",
        "/api/media",
        params={"name": "Spot iso"},
        files={"file": ("iso.png", png_bytes(), "image/png")},
    ).json()

    # Autre utilisateur de la même org : ne voit ni le média ni ne peut l'afficher.
    auth_json(
        client,
        "POST",
        "/api/users",
        json={
            "email": "other@iso.test",
            "password": "motdepasse-long",
            "full_name": "Autre",
            "role": "operator",
        },
    )
    login(client, "other@iso.test")
    listing = client.get("/api/media").json()
    assert all(m["id"] != media["id"] for m in listing)
    resp = auth_json(
        client,
        "POST",
        f"/api/media/{media['id']}/show",
        json={"device_id": enroll["device_id"]},
    )
    assert resp.status_code == 404


def test_add_to_playlist(client, settings, db_session_factory):
    env = setup(client)
    _ready_media(client, settings, db_session_factory, env["media"])
    playlist = auth_json(client, "POST", "/api/playlists", json={"name": "Boucle"}).json()

    resp = auth_json(
        client,
        "POST",
        f"/api/media/{env['media']['id']}/playlists/{playlist['id']}",
    )
    assert resp.status_code == 201, resp.text
    detail = client.get(f"/api/playlists/{playlist['id']}").json()
    assert len(detail["items"]) == 1
    assert detail["items"][0]["media_id"] == env["media"]["id"]
    assert detail["items"][0]["position"] == 1

    # Deuxième ajout : position incrémentée.
    resp2 = auth_json(
        client,
        "POST",
        f"/api/media/{env['media']['id']}/playlists/{playlist['id']}",
    )
    assert resp2.status_code == 201, resp2.text
    detail2 = client.get(f"/api/playlists/{playlist['id']}").json()
    assert len(detail2["items"]) == 2


def test_device_file_download(client, settings, db_session_factory):
    env = setup(client)
    _ready_media(client, settings, db_session_factory, env["media"])
    headers = {"Authorization": f"Bearer {env['token']}"}

    resp = client.get(f"/api/media/{env['media']['id']}/device-file", headers=headers)
    assert resp.status_code == 200
    assert resp.content == png_bytes()

    # Un device d'une autre organisation ne peut pas y accéder.
    login(client)  # superadmin admin@elyon.local
    org2 = create_org(client, "AutreOrg")
    login_as_org_admin(client, org2, "autre@org.test")
    site2 = auth_json(client, "POST", "/api/sites", json={"name": "Hall 2"}).json()
    token2 = auth_json(client, "POST", "/api/enroll/tokens", params={"site_id": site2["id"]}).json()
    enroll2 = client.post(
        "/api/enroll/request",
        json={"serial": "RPI-2", "name": "P2", "site_code": token2["code"]},
    ).json()
    auth_json(client, "POST", f"/api/devices/{enroll2['device_id']}/approve")
    resp2 = client.get(
        f"/api/media/{env['media']['id']}/device-file",
        headers={"Authorization": f"Bearer {enroll2['token']}"},
    )
    assert resp2.status_code == 404


def test_stop_show(client, settings, db_session_factory):
    env = setup(client)
    _ready_media(client, settings, db_session_factory, env["media"])

    shown = auth_json(
        client,
        "POST",
        f"/api/media/{env['media']['id']}/show",
        json={"device_id": env["device_id"]},
    )
    assert shown.status_code == 201, shown.text

    stopped = auth_json(
        client,
        "POST",
        f"/api/media/{env['media']['id']}/stop-show",
        json={"device_id": env["device_id"]},
    )
    assert stopped.status_code == 201, stopped.text

    commands = client.get(
        f"/api/devices/{env['device_id']}/commands",
        headers={"Authorization": f"Bearer {env['token']}"},
    ).json()
    types = [c["type"] for c in commands]
    # Le show est annulé côté serveur (jamais délivré) : seul stop_show part.
    assert types == ["stop_show"]


def test_wall_preview_requires_published_or_shown(client, settings, db_session_factory):
    env = setup(client)
    _ready_media(client, settings, db_session_factory, env["media"])

    # Média existant mais ni publié ni affiché → 404 (pas de fuite bibliothèque).
    denied = client.get(f"/api/admin/wall/preview/{env['media']['id']}")
    assert denied.status_code == 404

    # Après commande show → accessible à tout utilisateur connecté.
    auth_json(
        client,
        "POST",
        f"/api/media/{env['media']['id']}/show",
        json={"device_id": env["device_id"]},
    )
    allowed = client.get(f"/api/admin/wall/preview/{env['media']['id']}")
    assert allowed.status_code == 200
    assert allowed.content[:4] == b"\x89PNG"


def test_delete_playlist_removes_schedules_and_republishes(client, settings, db_session_factory):
    env = setup(client)
    _ready_media(client, settings, db_session_factory, env["media"])
    auth_json(
        client,
        "POST",
        f"/api/sites/{env['site']['id']}/screens",
        json={"name": "Écran 1", "device_id": env["device_id"]},
    )
    playlist = auth_json(client, "POST", "/api/playlists", json={"name": "Active"}).json()
    auth_json(
        client,
        "POST",
        f"/api/playlists/{playlist['id']}/items",
        json={"media_id": env["media"]["id"]},
    )
    auth_json(
        client,
        "POST",
        "/api/schedules",
        json={
            "site_id": env["site"]["id"],
            "playlist_id": playlist["id"],
            "name": "Permanente",
            "start_at": "2020-01-01T00:00:00Z",
            "end_at": "2099-01-01T00:00:00Z",
        },
    )
    published = auth_json(client, "POST", f"/api/devices/{env['device_id']}/publish")
    assert published.status_code == 200, published.text
    assert env["media"]["id"] in published.json()["payload"]

    # Suppression de la playlist → ses plannings disparaissent automatiquement.
    deleted = auth_json(client, "DELETE", f"/api/playlists/{playlist['id']}")
    assert deleted.status_code == 204, deleted.text

    schedules = client.get("/api/schedules").json()
    assert all(s["playlist_id"] != playlist["id"] for s in schedules)

    # L'écran est republié : le média n'est plus dans le manifeste.
    manifest = client.get(
        f"/api/devices/{env['device_id']}/manifest",
        headers={"Authorization": f"Bearer {env['token']}"},
    ).json()
    assert env["media"]["id"] not in manifest["payload"]


def test_unblock_device_requires_reenroll(client):
    env = setup(client)
    device_id = env["device_id"]
    blocked = auth_json(client, "POST", f"/api/devices/{device_id}/block")
    assert blocked.status_code == 200, blocked.text
    approve_refused = auth_json(client, "POST", f"/api/devices/{device_id}/approve")
    assert approve_refused.status_code == 409
    unblocked = auth_json(client, "POST", f"/api/devices/{device_id}/unblock")
    assert unblocked.status_code == 200, unblocked.text
    assert unblocked.json()["status"] == "pending"
    reapproved = auth_json(client, "POST", f"/api/devices/{device_id}/approve")
    assert reapproved.status_code == 200, reapproved.text
    assert reapproved.json()["status"] == "approved"
