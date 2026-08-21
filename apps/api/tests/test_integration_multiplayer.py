"""Intégration multi-player : deux players sur un même site.

Valide le parcours complet serveur :
enrôlement de deux devices → approbation → publication → manifestes
identiques et signés → isolation stricte des tokens entre devices.
"""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from elyon_api.models import DeviceStatus
from tests.conftest import (
    auth_json,
    bootstrap_superadmin,
    create_org,
    login,
    login_as_org_admin,
)

PNG_1PX = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def _create_site(client: TestClient, name: str) -> dict:
    response = auth_json(client, "POST", "/api/sites", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def _device_auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_two_players_same_site_concurrent_publish(client, settings, db_session_factory):
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, name="Acme")
    login_as_org_admin(client, org)
    site = _create_site(client, "Hall principal")

    # Jeton d'enrôlement à usage unique par player (1 code = 1 device).
    devices = []
    for player_name in ("Player hall", "Player accueil"):
        token_response = auth_json(
            client, "POST", "/api/enroll/tokens", params={"site_id": site["id"]}
        )
        assert token_response.status_code == 201, token_response.text
        enrolled = client.post(
            "/api/enroll/request",
            json={
                "serial": f"serial-{player_name}",
                "name": player_name,
                "site_code": token_response.json()["code"],
            },
        )
        assert enrolled.status_code == 201, enrolled.text
        devices.append(enrolled.json())

    # L'admin approuve les deux puis rattache chaque player à un écran du site
    # (le manifeste n'est construit que pour un device associé à un écran).
    for index, device in enumerate(devices):
        approval = auth_json(
            client, "POST", f"/api/devices/{device['device_id']}/approve"
        )
        assert approval.status_code == 200, approval.text
        screen = auth_json(
            client,
            "POST",
            f"/api/sites/{site['id']}/screens",
            json={"name": f"Écran {index + 1}", "device_id": device["device_id"]},
        )
        assert screen.status_code == 201, screen.text

    # Un média + une playlist + un planning actif sur le site.
    media = auth_json(
        client,
        "POST",
        "/api/media",
        params={"name": "Logo"},
        files={"file": ("logo.png", PNG_1PX, "image/png")},
    )
    assert media.status_code == 201, media.text
    media_id = media.json()["id"]

    # Traitement du média (le worker est hors bande dans les tests) → READY.
    from elyon_api.models import Media
    from elyon_api.services.media_processing import process_media
    from elyon_api.services.storage import LocalStorage

    with db_session_factory() as session:
        stored = session.get(Media, media_id)
        process_media(stored, settings, LocalStorage(settings.media_storage_root))
        session.commit()

    playlist = auth_json(client, "POST", "/api/playlists", json={"name": "Boucle"})
    assert playlist.status_code == 201, playlist.text
    playlist_id = playlist.json()["id"]

    item = auth_json(
        client,
        "POST",
        f"/api/playlists/{playlist_id}/items",
        json={"media_id": media_id, "duration_seconds": 6},
    )
    assert item.status_code == 201, item.text

    schedule = auth_json(
        client,
        "POST",
        "/api/schedules",
        json={
            "site_id": site["id"],
            "playlist_id": playlist_id,
            "name": "Permanente",
            "start_at": "2026-01-01T00:00:00Z",
            "end_at": "2027-01-01T00:00:00Z",
            "priority": 0,
        },
    )
    assert schedule.status_code == 201, schedule.text

    # Publication pour chaque player.
    manifests = []
    for device in devices:
        published = auth_json(
            client, "POST", f"/api/devices/{device['device_id']}/publish"
        )
        assert published.status_code in (200, 201), published.text
        fetched = client.get(
            f"/api/devices/{device['device_id']}/manifest",
            headers=_device_auth(device["token"]),
        )
        assert fetched.status_code == 200, fetched.text
        manifests.append(fetched.json())

    # Même version et même contenu de layout pour les deux players ; le payload
    # signé reste propre à chaque device (device_id, screen_id, published_at).
    assert manifests[0]["version"] == manifests[1]["version"]
    assert manifests[0]["signature"] != manifests[1]["signature"]

    def content(manifest: dict) -> dict:
        payload = json.loads(manifest["payload"])
        skip = ("device_id", "screen_id", "published_at")
        return {k: v for k, v in payload.items() if k not in skip}

    assert content(manifests[0]) == content(manifests[1])

    # Le layout embarque bien le planning du site.
    payload = json.loads(manifests[0]["payload"])
    blocks = payload.get("blocks", [])
    assert any(str(b.get("schedule_id")) == schedule.json()["id"] for b in blocks)
    assert blocks[0]["entries"][0]["media_id"] == media_id

    # Isolation : le token du player A ne peut pas lire le manifeste du B.
    cross = client.get(
        f"/api/devices/{devices[1]['device_id']}/manifest",
        headers=_device_auth(devices[0]["token"]),
    )
    assert cross.status_code in (401, 403)

    # Les deux devices sont approuvés côté base.
    listing = client.get("/api/devices")
    statuses = {d["id"]: d["status"] for d in listing.json()}
    assert all(statuses[d["device_id"]] == DeviceStatus.APPROVED.value for d in devices)
