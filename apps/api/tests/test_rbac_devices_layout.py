"""Non-régression : accès page Devices par rôle + isolation org/site + audit publish."""

from __future__ import annotations

from fastapi.testclient import TestClient

from elyon_api.models import Role
from tests.conftest import auth_json, bootstrap_superadmin, create_org, login


def _login_as(client: TestClient, org: dict, role: Role, site_id: str | None = None) -> None:
    import uuid as _uuid
    email = f"{role.value}-{_uuid.uuid4().hex[:6]}@test.local"
    body: dict = {
        "email": email,
        "password": "motdepasse-long",
        "full_name": f"User {role.value}",
        "role": role.value,
        "org_id": org["id"],
    }
    if site_id is not None:
        body["site_id"] = site_id
    resp = auth_json(client, "POST", "/api/users", json=body)
    assert resp.status_code == 201, resp.text
    login(client, email)


def _setup_two_orgs_two_sites(client: TestClient):
    bootstrap_superadmin(client)
    login(client)
    org_a = create_org(client, "OrgA")
    org_b = create_org(client, "OrgB")
    # Sites créés par org_admin dédié (superadmin ne peut pas)
    from tests.conftest import login_as_org_admin
    login_as_org_admin(client, org_a, "orga@orga.test")
    site_a = auth_json(client, "POST", "/api/sites", json={"name": "SiteA"}).json()
    login(client, "admin@elyon.local", "motdepasse-long")
    login_as_org_admin(client, org_b, "orgb@orgb.test")
    site_b = auth_json(client, "POST", "/api/sites", json={"name": "SiteB"}).json()
    # Revenir superadmin pour créer les users de test
    login(client, "admin@elyon.local", "motdepasse-long")
    return org_a, org_b, site_a, site_b


def _create_site_manager_for_site(client: TestClient, org: dict, site_id: str) -> str:
    import uuid as _uuid2
    email = f"site_manager-{_uuid2.uuid4().hex[:6]}@test.local"
    login(client, "admin@elyon.local", "motdepasse-long")
    resp = auth_json(client, "POST", "/api/users", json={
        "email": email, "password": "motdepasse-long", "full_name": "Site Manager",
        "role": Role.SITE_MANAGER.value, "org_id": org["id"], "site_id": site_id,
    })
    assert resp.status_code == 201, resp.text
    return email


def _create_users_for_org(client: TestClient, org: dict, site_id: str) -> dict[Role, str]:
    """Crée un utilisateur par rôle (emails uniques) et retourne mapping role→email."""
    emails: dict[Role, str] = {}
    for role, site in [
        (Role.ORG_ADMIN, None),
        (Role.SITE_MANAGER, site_id),
        (Role.OPERATOR, site_id),
        (Role.VIEWER, site_id),
    ]:
        import uuid as _uuid2
        email = f"{role.value}-dev-{_uuid2.uuid4().hex[:6]}@test.local"
        body: dict = {
            "email": email,
            "password": "motdepasse-long",
            "full_name": f"User {role.value}",
            "role": role.value,
            "org_id": org["id"],
        }
        if site is not None:
            body["site_id"] = site
        # Création par superadmin (évite Permission manquante)
        login(client, "admin@elyon.local", "motdepasse-long")
        resp = auth_json(client, "POST", "/api/users", json=body)
        assert resp.status_code == 201, resp.text
        emails[role] = email
    return emails


def test_devices_page_accessible_for_all_authorized_roles(client: TestClient):
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "OrgDevices")
    # Site + users créés par superadmin
    site_resp = auth_json(client, "POST", "/api/sites", json={"name": "SiteD"})
    # superadmin cannot create site → use org_admin bootstrap
    if site_resp.status_code == 400:
        # fallback: create via org_admin helper
        from tests.conftest import login_as_org_admin
        login_as_org_admin(client, org, "org-devices@org.test")
        site_resp = auth_json(client, "POST", "/api/sites", json={"name": "SiteD"})
    assert site_resp.status_code == 201, site_resp.text
    site_id = site_resp.json()["id"]
    # Crée tous les utilisateurs depuis superadmin, puis teste chaque login
    login(client, "admin@elyon.local", "motdepasse-long")
    emails = _create_users_for_org(client, org, site_id)
    for role, email in emails.items():
        login(client, email, "motdepasse-long")
        resp = client.get("/api/devices")
        assert resp.status_code == 200, f"{role} GET /devices: {resp.text}"
        resp = client.get(f"/api/sites/{site_id}/screens")
        assert resp.status_code == 200, f"{role} list screens: {resp.text}"
        if role == Role.VIEWER:
            resp = auth_json(
                client, "POST", f"/api/sites/{site_id}/screens",
                json={"name": f"Ecran-{role.value}"},
            )
            assert resp.status_code == 403, f"viewer should not create screen: {resp.text}"


def test_users_isolation_org_and_site(client: TestClient):
    org_a, org_b, site_a, site_b = _setup_two_orgs_two_sites(client)
    email = _create_site_manager_for_site(client, org_a, site_a["id"])
    login(client, email, "motdepasse-long")
    # Ne doit pas voir site B (autre org)
    resp = client.get(f"/api/sites/{site_b['id']}")
    assert resp.status_code in (403, 404)
    # Ne doit pas voir users de l'autre org
    users = client.get("/api/users").json()
    assert all(u["org_id"] == org_a["id"] or u["role"] == "superadmin" for u in users)


def test_rbac_granular_viewer_cannot_mutate(client: TestClient):
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "OrgRBAC")
    from tests.conftest import login_as_org_admin
    login_as_org_admin(client, org, "rbac@org.test")
    site = auth_json(client, "POST", "/api/sites", json={"name": "SiteR"}).json()
    assert "id" in site, site
    _create_site_manager_for_site(client, org, site["id"])
    login(client, "admin@elyon.local", "motdepasse-long")
    import uuid as _uuid3
    viewer_email2 = f"viewer-{_uuid3.uuid4().hex[:6]}@test.local"
    auth_json(client, "POST", "/api/users", json={
        "email": viewer_email2, "password": "motdepasse-long", "full_name": "Viewer",
        "role": Role.VIEWER.value, "org_id": org["id"], "site_id": site["id"],
    })
    login(client, viewer_email2, "motdepasse-long")
    # VIEWER cannot publish / create playlist / upload
    for method, path, body in [
        ("POST", "/api/playlists", {"name": "PL"}),
        ("POST", "/api/schedules", {"site_id": site["id"], "playlist_id": "000", "name": "S", "start_at": "2026-01-01T00:00:00Z", "end_at": "2027-01-01T00:00:00Z"}),
    ]:
        resp = auth_json(client, method, path, json=body)
        assert resp.status_code == 403, f"viewer {method} {path}: {resp.text}"
    # VIEWER cannot approve device
    resp = auth_json(client, "POST", "/api/devices/00000000000000000000000000000000/approve")
    assert resp.status_code in (403, 404)


def test_publish_is_audited(client: TestClient, db_session_factory):
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "OrgAudit")
    from tests.conftest import login_as_org_admin
    login_as_org_admin(client, org, "audit@org.test")
    site = auth_json(client, "POST", "/api/sites", json={"name": "SiteAudit"}).json()
    # Device + approve + screen
    tok = auth_json(client, "POST", "/api/enroll/tokens", params={"site_id": site["id"]}).json()
    dev = client.post(
        "/api/enroll/request",
        json={"serial": "SER-AUDIT-1", "name": "DevAudit", "site_code": tok["code"]},
    ).json()
    auth_json(client, "POST", f"/api/devices/{dev['device_id']}/approve")
    screen = auth_json(
        client, "POST", f"/api/sites/{site['id']}/screens",
        json={"name": "EcranAudit", "device_id": dev["device_id"]},
    ).json()
    # Publish doit créer un audit log
    resp = auth_json(client, "POST", f"/api/devices/{dev['device_id']}/publish")
    assert resp.status_code in (200, 201), resp.text
    from elyon_api.models import AuditLog
    with db_session_factory() as s:
        logs = s.query(AuditLog).filter(AuditLog.action == "manifest.publish").all()
        assert len(logs) >= 1
        assert any(log.resource_id == dev["device_id"] for log in logs)


def test_layout_validation_and_manifest_inclusion(client: TestClient):
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "OrgLayout")
    from tests.conftest import login_as_org_admin
    login_as_org_admin(client, org, "layout@org.test")
    site = auth_json(client, "POST", "/api/sites", json={"name": "SiteLayout"}).json()
    screen = auth_json(
        client, "POST", f"/api/sites/{site['id']}/screens", json={"name": "EcranL"}
    ).json()
    # Layout invalide (w hors borne) → 422
    bad = auth_json(
        client, "PATCH", f"/api/screens/{screen['id']}",
        json={"layout": {"mode": "custom", "zones": [{"x": 0, "y": 0, "w": 200, "h": 100}]}},
    )
    assert bad.status_code == 422
    # Layout valide
    good = auth_json(
        client, "PATCH", f"/api/screens/{screen['id']}",
        json={"layout": {"mode": "grid_2x2", "zones": [
            {"x": 0, "y": 0, "w": 50, "h": 50},
            {"x": 50, "y": 0, "w": 50, "h": 50},
            {"x": 0, "y": 50, "w": 50, "h": 50},
            {"x": 50, "y": 50, "w": 50, "h": 50},
        ]}},
    )
    assert good.status_code == 200, good.text
    assert good.json()["layout"]["mode"] == "grid_2x2"
    # Manifeste doit inclure le layout
    tok = auth_json(client, "POST", "/api/enroll/tokens", params={"site_id": site["id"]}).json()
    dev = client.post(
        "/api/enroll/request",
        json={"serial": "SER-LAYOUT-1", "name": "DevL", "site_code": tok["code"]},
    ).json()
    auth_json(client, "POST", f"/api/devices/{dev['device_id']}/approve")
    auth_json(client, "PATCH", f"/api/screens/{screen['id']}", json={"device_id": dev["device_id"]})
    mf = auth_json(client, "POST", f"/api/devices/{dev['device_id']}/publish").json()
    import json as _json
    payload = _json.loads(mf["payload"])
    assert payload["layout"] is not None
    assert payload["layout"]["mode"] == "grid_2x2"
