from __future__ import annotations

from tests.conftest import (
    auth_json,
    bootstrap_superadmin,
    create_org,
    login,
    login_as_org_admin,
)


def setup_device(client, serial="RPI-O1") -> dict:
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "OpsCo")
    login_as_org_admin(client, org, "ops@org.test")
    site = auth_json(client, "POST", "/api/sites", json={"name": "Site 1"}).json()
    token = auth_json(client, "POST", "/api/enroll/tokens", params={"site_id": site["id"]}).json()
    enroll = client.post(
        "/api/enroll/request",
        json={"serial": serial, "name": "P", "site_code": token["code"]},
    ).json()
    auth_json(client, "POST", f"/api/devices/{enroll['device_id']}/approve")
    return {**enroll, "site": site}


def test_heartbeat_and_events(client):
    env = setup_device(client)
    hb = client.post(
        f"/api/devices/{env['device_id']}/heartbeat",
        headers={"Authorization": f"Bearer {env['token']}"},
        json={"state": "playing", "current_media_id": "m1"},
    )
    assert hb.status_code == 200
    assert hb.json()["heartbeat_interval_seconds"] == 30
    events = client.get("/api/events").json()
    assert any(e["type"] == "device_online" for e in events)


def test_commands_flow(client):
    env = setup_device(client)
    issue = auth_json(
        client,
        "POST",
        f"/api/devices/{env['device_id']}/commands",
        json={"type": "reboot"},
    )
    assert issue.status_code == 201, issue.text
    command_id = issue.json()["id"]

    pending = client.get(
        f"/api/devices/{env['device_id']}/commands",
        headers={"Authorization": f"Bearer {env['token']}"},
    )
    assert pending.status_code == 200
    assert [c["id"] for c in pending.json()] == [command_id]

    ack = client.post(
        f"/api/devices/{env['device_id']}/commands/{command_id}/ack",
        headers={"Authorization": f"Bearer {env['token']}"},
        json={},
    )
    assert ack.status_code == 200

    empty = client.get(
        f"/api/devices/{env['device_id']}/commands",
        headers={"Authorization": f"Bearer {env['token']}"},
    )
    assert empty.json() == []

    issue2 = auth_json(
        client,
        "POST",
        f"/api/devices/{env['device_id']}/commands",
        json={"type": "resync"},
    )
    ack_fail = client.post(
        f"/api/devices/{env['device_id']}/commands/{issue2.json()['id']}/ack",
        headers={"Authorization": f"Bearer {env['token']}"},
        json={"error": "mpv crashed"},
    )
    assert ack_fail.status_code == 200
    events = client.get("/api/events").json()
    assert any(e["type"] == "command_failed" for e in events)


def test_dashboard(client):
    setup_device(client)
    dash = client.get("/api/dashboard")
    assert dash.status_code == 200
    body = dash.json()
    assert body["devices_total"] == 1
    assert body["devices_pending"] == 0
    assert "recent_events" in body


def test_viewer_cannot_issue_commands(client):
    env = setup_device(client)
    create_user = auth_json(
        client,
        "POST",
        "/api/users",
        json={
            "email": "viewer@ops.test",
            "password": "motdepasse-long",
            "full_name": "V",
            "role": "viewer",
        },
    )
    assert create_user.status_code == 201
    login(client, "viewer@ops.test")
    resp = auth_json(
        client,
        "POST",
        f"/api/devices/{env['device_id']}/commands",
        json={"type": "reboot"},
    )
    assert resp.status_code == 403