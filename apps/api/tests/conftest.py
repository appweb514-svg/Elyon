from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from elyon_api.config import Settings
from elyon_api.db import build_engine, sessionmaker
from elyon_api.main import create_app
from elyon_api.models import Base


@pytest.fixture()
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        media_storage_root=tmp_path / "media",
        signing_key_file=tmp_path / "signing.pem",
        session_secret="test-secret",
        public_base_url="http://testserver",
        auto_migrate=False,
        enqueue_media_processing=False,
        session_cookie_name="elyon_session",
        csrf_cookie_name="elyon_csrf",
    )


@pytest.fixture()
def db_session_factory(settings: Settings):
    engine = build_engine(settings)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    return factory


@pytest.fixture()
def app(settings: Settings, db_session_factory):
    application = create_app(settings, run_migrations=False)
    application.state.session_factory = db_session_factory
    return application


@pytest.fixture()
def client(app):
    return TestClient(app)


def login(
    client: TestClient, email: str = "admin@elyon.local", password: str = "motdepasse-long"
) -> None:
    response = client.post("/api/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200, response.text


def csrf_headers(client: TestClient) -> dict:
    return {"X-CSRF-Token": client.cookies.get("elyon_csrf", "")}


def bootstrap_superadmin(client: TestClient) -> None:
    response = client.post(
        "/api/auth/bootstrap",
        json={"email": "admin@elyon.local", "password": "motdepasse-long"},
    )
    assert response.status_code == 201, response.text


def auth_json(client: TestClient, method: str, path: str, **kwargs):
    headers = kwargs.pop("headers", {})
    headers.update(csrf_headers(client))
    return client.request(method, path, headers=headers, **kwargs)


def create_org(client: TestClient, name: str = "Acme") -> dict:
    response = auth_json(
        client,
        "POST",
        "/api/organizations",
        params={"name": name, "slug": name.lower()},
    )
    assert response.status_code == 201, response.text
    return response.json()


def login_as_org_admin(client: TestClient, org: dict, email: str = "admin@org.test") -> None:
    response = auth_json(
        client,
        "POST",
        "/api/users",
        json={
            "email": email,
            "password": "motdepasse-long",
            "full_name": "Admin Org",
            "role": "org_admin",
            "org_id": org["id"],
        },
    )
    assert response.status_code == 201, response.text
    login(client, email)