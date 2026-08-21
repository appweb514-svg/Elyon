from __future__ import annotations

from tests.conftest import (
    auth_json,
    bootstrap_superadmin,
    create_org,
    login,
    login_as_org_admin,
)


def setup_org_site(client) -> dict:
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "EnrollCo")
    login_as_org_admin(client, org, "enroll@org.test")
    site = auth_json(client, "POST", "/api/sites", json={"name": "Site 1"})
    assert site.status_code == 201, site.text
    return org, site.json()


def test_enroll_flow(client, db_session_factory):
    org, site = setup_org_site(client)
    token_resp = auth_json(
        client, "POST", "/api/enroll/tokens", params={"site_id": site["id"]}
    )
    assert token_resp.status_code == 201, token_resp.text
    token = token_resp.json()
    assert len(token["code"]) == 6

    enroll = client.post(
        "/api/enroll/request",
        json={
            "serial": "RPI-0001",
            "name": "Hall d'entrée",
            "site_code": token["code"],
            "public_key": "-----BEGIN PUBLIC KEY-----\nABC\n-----END PUBLIC KEY-----",
        },
    )
    assert enroll.status_code == 201, enroll.text
    creds = enroll.json()
    assert creds["token"]

    devices = client.get("/api/devices")
    assert devices.status_code == 200
    device = next(d for d in devices.json() if d["serial"] == "RPI-0001")
    assert device["status"] == "pending"
    assert device["site_id"] == site["id"]

    screen = auth_json(
        client,
        "POST",
        f"/api/sites/{site['id']}/screens",
        json={"name": "Écran 1", "width": 1920, "height": 1080},
    )
    assert screen.status_code == 201

    approve = auth_json(client, "POST", f"/api/devices/{device['id']}/approve")
    assert approve.status_code == 200
    assert approve.json()["status"] == "approved"

    heartbeat = client.post(
        f"/api/devices/{device['id']}/heartbeat",
        headers={"Authorization": f"Bearer {creds['token']}"},
        json={"state": "playing"},
    )
    assert heartbeat.status_code == 200

    with db_session_factory() as session:
        from sqlalchemy import select

        from elyon_api.models import Device

        stored = session.scalar(select(Device).where(Device.serial == "RPI-0001"))
        assert stored.last_seen_at is not None

    rotate = auth_json(client, "POST", f"/api/devices/{device['id']}/rotate-token")
    assert rotate.status_code == 200

    old_heartbeat = client.post(
        f"/api/devices/{device['id']}/heartbeat",
        headers={"Authorization": f"Bearer {creds['token']}"},
        json={"state": "playing"},
    )
    assert old_heartbeat.status_code == 401

    new_heartbeat = client.post(
        f"/api/devices/{device['id']}/heartbeat",
        headers={"Authorization": f"Bearer {rotate.json()['token']}"},
        json={"state": "playing"},
    )
    assert new_heartbeat.status_code == 200

    block = auth_json(client, "POST", f"/api/devices/{device['id']}/block")
    assert block.status_code == 200
    blocked_hb = client.post(
        f"/api/devices/{device['id']}/heartbeat",
        headers={"Authorization": f"Bearer {rotate.json()['token']}"},
        json={"state": "playing"},
    )
    assert blocked_hb.status_code in (401, 403)


def test_enroll_wrong_code(client):
    setup_org_site(client)
    enroll = client.post(
        "/api/enroll/request",
        json={"serial": "RPI-0002", "name": "P2", "site_code": "XXXXXX"},
    )
    assert enroll.status_code == 401


def test_enroll_token_used_once(client):
    org, site = setup_org_site(client)
    token = auth_json(client, "POST", "/api/enroll/tokens", params={"site_id": site["id"]}).json()
    first = client.post(
        "/api/enroll/request",
        json={"serial": "RPI-0003", "name": "P3", "site_code": token["code"]},
    )
    assert first.status_code == 201
    second = client.post(
        "/api/enroll/request",
        json={"serial": "RPI-0004", "name": "P4", "site_code": token["code"]},
    )
    assert second.status_code == 401


def test_screen_requires_same_org(client):
    org, site = setup_org_site(client)
    login(client, "admin@elyon.local")
    other_org = create_org(client, "Autre")
    resp = auth_json(
        client,
        "POST",
        "/api/users",
        json={
            "email": "boss@autre.test",
            "password": "motdepasse-long",
            "full_name": "B",
            "role": "org_admin",
            "org_id": other_org["id"],
        },
    )
    assert resp.status_code == 201
    login(client, "boss@autre.test")
    resp = auth_json(
        client,
        "POST",
        f"/api/sites/{site['id']}/screens",
        json={"name": "X"},
    )
    assert resp.status_code == 403