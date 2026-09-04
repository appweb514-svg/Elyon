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
    assert "devices_offline" in body
    assert "media_ready" in body
    assert "media_bytes" in body
    assert "events_24h" in body
    assert "events_warning_24h" in body
    assert "recent_events" in body


def test_audit_logs(client):
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "AuditCo")
    login_as_org_admin(client, org, "audit@org.test")
    site = auth_json(client, "POST", "/api/sites", json={"name": "S1"}).json()
    page = client.get("/api/audit/logs?limit=20&offset=0")
    assert page.status_code == 200
    body = page.json()
    assert body["total"] > 0
    entries = body["items"]
    created_site = next(e for e in entries if e["action"] == "site.create")
    assert created_site["resource_type"] == "site"
    assert created_site["resource_id"] == site["id"]
    by_action = client.get("/api/audit/logs?action=site.create&limit=20").json()
    assert {e["resource_id"] for e in by_action["items"]} == {site["id"]}
    # Pagination : bornes cohérentes.
    paged = client.get("/api/audit/logs?limit=50&offset=0").json()
    assert paged["limit"] == 50
    assert len(paged["items"]) <= 50


def test_superadmin_media_upload_requires_and_accepts_target_org(client):
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "MediaCo")

    missing_org = auth_json(
        client,
        "POST",
        "/api/media",
        files={"file": ("tiny.png", b"not-empty", "image/png")},
    )
    assert missing_org.status_code == 201, missing_org.text
    assert missing_org.json()["org_id"] == org["id"]

    uploaded = auth_json(
        client,
        "POST",
        "/api/media",
        data={"org_id": org["id"], "name": "Logo"},
        files={"file": ("tiny.png", b"not-empty", "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["org_id"] == org["id"]


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
