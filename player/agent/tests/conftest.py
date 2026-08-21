from __future__ import annotations

import io

import pytest
from elyon_api.config import Settings
from elyon_api.db import build_engine, sessionmaker
from elyon_api.main import create_app
from elyon_api.models import Base
from fastapi.testclient import TestClient

from elyon_agent.config import AgentSettings
from elyon_agent.state import DeviceState


@pytest.fixture()
def api_settings(tmp_path):
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        media_storage_root=tmp_path / "media",
        signing_key_file=tmp_path / "signing.pem",
        session_secret="test-secret",
        public_base_url="http://testserver",
        auto_migrate=False,
        session_cookie_name="elyon_session",
        csrf_cookie_name="elyon_csrf",
    )


@pytest.fixture()
def app(api_settings):
    engine = build_engine(api_settings)
    Base.metadata.create_all(engine)
    application = create_app(api_settings, run_migrations=False)
    application.state.session_factory = sessionmaker(
        bind=engine, autoflush=False, expire_on_commit=False
    )
    application.state._test_engine = engine
    return application


@pytest.fixture()
def db_session_factory(app):
    return app.state.session_factory


@pytest.fixture()
def api(app):
    return TestClient(app)


@pytest.fixture()
def agent_settings(tmp_path):
    return AgentSettings(
        server_url="http://testserver",
        state_file=tmp_path / "state.json",
        data_dir=tmp_path,
    )


def admin_login(api: TestClient) -> None:
    response = api.post(
        "/api/auth/bootstrap",
        json={"email": "admin@elyon.local", "password": "motdepasse-long"},
    )
    assert response.status_code in (201, 403), response.text
    response = api.post(
        "/api/auth/login",
        json={"email": "admin@elyon.local", "password": "motdepasse-long"},
    )
    assert response.status_code == 200, response.text


def csrf_headers(api: TestClient) -> dict:
    return {"X-CSRF-Token": api.cookies.get("elyon_csrf", "")}


def bootstrap_site(api: TestClient, name: str = "Acme") -> tuple[str, str, str]:
    """Crée org + admin org + site + token d'enrôlement ; retourne (org_id, site_id, code)."""
    import secrets as _secrets

    slug = f"{name.lower()}-{_secrets.token_hex(4)}"
    email = f"admin@{slug}.test"
    org = api.post(
        "/api/organizations",
        params={"name": name, "slug": slug},
        headers=csrf_headers(api),
    )
    assert org.status_code == 201, org.text
    org_id = org.json()["id"]
    user = api.post(
        "/api/users",
        json={
            "email": email,
            "password": "motdepasse-long",
            "full_name": f"Admin {name}",
            "role": "org_admin",
            "org_id": org_id,
        },
        headers=csrf_headers(api),
    )
    assert user.status_code == 201, user.text
    login_response = api.post(
        "/api/auth/login",
        json={"email": email, "password": "motdepasse-long"},
    )
    assert login_response.status_code == 200, login_response.text
    site = api.post(
        "/api/sites",
        json={"name": "Hall A"},
        headers=csrf_headers(api),
    )
    assert site.status_code == 201, site.text
    site_id = site.json()["id"]
    token = api.post(
        "/api/enroll/tokens", params={"site_id": site_id}, headers=csrf_headers(api)
    )
    assert token.status_code == 201, token.text
    return org_id, site_id, token.json()["code"]


def enroll_device(api: TestClient, code: str) -> dict:
    response = api.post(
        "/api/enroll/request",
        json={"serial": "pi-0001", "name": "Hall A — Entrée", "site_code": code},
    )
    assert response.status_code == 201, response.text
    return response.json()


def approve_device(api: TestClient, device_id: str) -> None:
    response = api.post(f"/api/devices/{device_id}/approve", headers=csrf_headers(api))
    assert response.status_code == 200, response.text


@pytest.fixture()
def enrolled(api):
    """Player enrôlé et approuvé ; retourne (org_id, site_id, device_id, token)."""
    admin_login(api)
    org_id, site_id, code = bootstrap_site(api)
    device = enroll_device(api, code)
    approve_device(api, device["device_id"])
    return org_id, site_id, device["device_id"], device["token"]


@pytest.fixture()
def device_state(enrolled):
    _, _, device_id, token = enrolled
    return DeviceState(device_id=device_id, token=token)


@pytest.fixture()
def agent_io():
    inputs = io.StringIO()
    outputs = io.StringIO()
    return inputs, outputs
