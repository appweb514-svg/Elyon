"""Groupes d'appareils, trigger d'urgence et proof-of-play."""

from __future__ import annotations

import io

from elyon_api.models import Media, PlaybackEvent
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
    Image.new("RGB", (16, 16), (80, 120, 200)).save(buf, "PNG")
    return buf.getvalue()


def setup(client) -> dict:
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "GrpCo")
    login_as_org_admin(client, org, "grp@org.test")
    site = auth_json(client, "POST", "/api/sites", json={"name": "Site G"}).json()
    devices = []
    for i in range(2):
        token = auth_json(
            client, "POST", "/api/enroll/tokens", params={"site_id": site["id"]}
        ).json()
        enroll = client.post(
            "/api/enroll/request",
            json={"serial": f"RPI-G{i}", "name": f"Pi G{i}", "site_code": token["code"]},
        ).json()
        auth_json(client, "POST", f"/api/devices/{enroll['device_id']}/approve")
        devices.append(enroll)
    return {"site": site, "devices": devices}


def test_device_groups_and_bulk_command(client):
    env = setup(client)
    d1, d2 = env["devices"]
    created = auth_json(
        client,
        "POST",
        "/api/device-groups",
        params={"name": "Vitrine"},
        json=[d1["device_id"], d2["device_id"]],
    )
    assert created.status_code == 201, created.text
    group = created.json()
    assert sorted(group["device_ids"]) == sorted([d1["device_id"], d2["device_id"]])

    # Commande groupée → une commande par appareil.
    sent = auth_json(
        client,
        "POST",
        f"/api/device-groups/{group['id']}/commands",
        json={"type": "reboot"},
    )
    assert sent.status_code == 201, sent.text
    assert sent.json()["devices"] == 2
    for dev in (d1, d2):
        cmds = client.get(
            f"/api/devices/{dev['device_id']}/commands",
            headers={"Authorization": f"Bearer {dev['token']}"},
        ).json()
        assert any(c["type"] == "reboot" for c in cmds)

    # Suppression du groupe.
    deleted = auth_json(client, "DELETE", f"/api/device-groups/{group['id']}")
    assert deleted.status_code == 204


def test_trigger_show_with_secret(client, settings, db_session_factory):
    env = setup(client)
    settings.trigger_secret = "super-secret"
    media = auth_json(
        client,
        "POST",
        "/api/media",
        files={"file": ("s.png", png_bytes(), "image/png")},
    ).json()
    with db_session_factory() as session:
        stored = session.get(Media, media["id"])
        process_media(stored, settings, LocalStorage(settings.media_storage_root))
        session.commit()
    device = env["devices"][0]

    # Sans secret → 403.
    no_auth = client.post(
        f"/api/trigger/{device['device_id']}/show",
        json={"media_id": media["id"]},
    )
    assert no_auth.status_code == 403

    # Avec le bon secret → commande show créée.
    ok = client.post(
        f"/api/trigger/{device['device_id']}/show",
        headers={"X-Trigger-Secret": "super-secret"},
        json={"media_id": media["id"]},
    )
    assert ok.status_code == 200, ok.text
    assert ok.json()["media_id"] == media["id"]
    cmds = client.get(
        f"/api/devices/{device['device_id']}/commands",
        headers={"Authorization": f"Bearer {device['token']}"},
    ).json()
    assert any(c["type"] == "show" for c in cmds)


def test_trigger_requires_configured_secret(client, settings):
    settings.trigger_secret = ""
    env = setup(client)
    device = env["devices"][0]
    # Secret non configuré (défaut vide) → endpoint indisponible.
    resp = client.post(
        f"/api/trigger/{device['device_id']}/show",
        headers={"X-Trigger-Secret": "x"},
        json={"media_id": "y"},
    )
    assert resp.status_code == 404


def test_playback_events_recorded(client, settings, db_session_factory):
    env = setup(client)
    media = auth_json(
        client,
        "POST",
        "/api/media",
        files={"file": ("p.png", png_bytes(), "image/png")},
    ).json()
    with db_session_factory() as session:
        stored = session.get(Media, media["id"])
        process_media(stored, settings, LocalStorage(settings.media_storage_root))
        session.commit()
    device = env["devices"][0]

    client.post(
        f"/api/devices/{device['device_id']}/heartbeat",
        headers={"Authorization": f"Bearer {device['token']}"},
        json={"state": "playing", "current_media_id": media["id"]},
    )

    with db_session_factory() as session:
        events = session.query(PlaybackEvent).all()
        assert len(events) == 1
        assert events[0].media_id == media["id"]
        assert events[0].state == "playing"

    # Export CSV.
    csv = client.get("/api/admin/playback/export")
    assert csv.status_code == 200
    assert "horodatage,appareil,media,etat" in csv.text
    assert "p.png" in csv.text
