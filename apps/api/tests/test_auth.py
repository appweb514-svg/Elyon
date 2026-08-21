from __future__ import annotations

from tests.conftest import (
    auth_json,
    bootstrap_superadmin,
    create_org,
    csrf_headers,
    login,
    login_as_org_admin,
)


def test_bootstrap_then_forbidden(client):
    bootstrap_superadmin(client)
    response = client.post(
        "/api/auth/bootstrap",
        json={"email": "autre@elyon.local", "password": "motdepasse-long"},
    )
    assert response.status_code == 403


def test_login_and_me(client):
    bootstrap_superadmin(client)
    login(client)
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["email"] == "admin@elyon.local"
    assert body["role"] == "superadmin"


def test_login_wrong_password(client):
    bootstrap_superadmin(client)
    response = client.post(
        "/api/auth/login", json={"email": "admin@elyon.local", "password": "mauvais-mdp"}
    )
    assert response.status_code == 401


def test_csrf_required(client):
    bootstrap_superadmin(client)
    login(client)
    response = client.post(
        "/api/organizations", params={"name": "X", "slug": "x"}
    )
    assert response.status_code == 403
    response = auth_json(
        client, "POST", "/api/organizations", params={"name": "X", "slug": "x"}
    )
    assert response.status_code == 201


def test_roles_and_scoping(client):
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "Acme")
    viewer = auth_json(
        client,
        "POST",
        "/api/users",
        json={
            "email": "viewer@acme.test",
            "password": "motdepasse-long",
            "full_name": "V",
            "role": "viewer",
            "org_id": org["id"],
        },
    )
    assert viewer.status_code == 201, viewer.text

    org_admin = auth_json(
        client,
        "POST",
        "/api/users",
        json={
            "email": "admin@acme.test",
            "password": "motdepasse-long",
            "full_name": "A",
            "role": "org_admin",
            "org_id": org["id"],
        },
    )
    assert org_admin.status_code == 201

    login(client, "viewer@acme.test")
    denied = client.post(
        "/api/organizations", headers=csrf_headers(client),
        params={"name": "Nope", "slug": "nope"},
    )
    assert denied.status_code in (403, 404, 405)
    sites = client.get("/api/sites")
    assert sites.status_code == 200

    login(client, "admin@acme.test")
    sites = client.get("/api/sites")
    assert sites.status_code == 200
    site = auth_json(
        client,
        "POST",
        "/api/sites",
        json={"name": "Site 1", "timezone": "Europe/Paris"},
    )
    assert site.status_code == 201, site.text

    login(client)
    other_org_site = client.get(f"/api/sites/{site.json()['id']}")
    assert other_org_site.status_code == 200

    login(client, "admin@acme.test")
    other_org_site = client.get(f"/api/sites/{site.json()['id']}")
    assert other_org_site.status_code == 200

    login(client, "viewer@acme.test")
    other_org_site = client.get(f"/api/sites/{site.json()['id']}")
    assert other_org_site.status_code == 200

    login(client)
    other_org = create_org(client, "Rivale")
    login_as_org_admin(client, other_org, "rival@rivale.test")
    rival_site = auth_json(
        client,
        "POST",
        "/api/sites",
        json={"name": "Site rival", "timezone": "Europe/Paris"},
    )
    assert rival_site.status_code == 201

    login(client, "viewer@acme.test")
    other_org_site = client.get(f"/api/sites/{rival_site.json()['id']}")
    assert other_org_site.status_code == 403


def test_audit_log_written(client, db_session_factory):
    bootstrap_superadmin(client)
    login(client)
    create_org(client, "AuditCo")
    with db_session_factory() as session:
        from sqlalchemy import select

        from elyon_api.models import AuditLog

        logs = session.scalars(select(AuditLog)).all()
        actions = {log.action for log in logs}
        assert "user.bootstrap" in actions
        assert "auth.login" in actions
        assert "organization.create" in actions


def test_cannot_create_superadmin(client):
    bootstrap_superadmin(client)
    login(client)
    org = create_org(client, "Acme")
    login_as_org_admin(client, org, "boss@acme.test")
    response = auth_json(
        client,
        "POST",
        "/api/users",
        json={
            "email": "evil@acme.test",
            "password": "motdepasse-long",
            "full_name": "E",
            "role": "superadmin",
            "org_id": org["id"],
        },
    )
    assert response.status_code == 403