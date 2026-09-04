from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from elyon_agent.run import refresh_widget_feed
from tests.conftest import admin_login, approve_device, bootstrap_site, csrf_headers, enroll_device


@pytest.fixture()
def enrolled_site(api):
    """Org + site + device enrôlé et approuvé (token inclus)."""
    admin_login(api)
    org_id, site_id, code = bootstrap_site(api)
    device = enroll_device(api, code)
    approve_device(api, device["device_id"])
    return org_id, site_id, device["device_id"], device["token"]


def test_widgets_feed_requires_device_token(api: TestClient, enrolled_site):
    _, _, device_id, _ = enrolled_site
    response = api.get(f"/api/devices/{device_id}/widgets")
    assert response.status_code in (401, 403)


def test_widgets_feed_text_clock_no_external_calls(api: TestClient, enrolled_site):
    _, site_id, device_id, token = enrolled_site
    screen = api.post(
        f"/api/sites/{site_id}/screens",
        json={"name": "Écran 1", "width": 1920, "height": 1080, "device_id": device_id},
        headers=csrf_headers(api),
    )
    assert screen.status_code == 201, screen.text
    patch = api.patch(
        f"/api/screens/{screen.json()['id']}",
        json={
            "widgets": [
                {"type": "text", "position": "bottom-left", "visible": True,
                 "params": {"text": "Bienvenue"}},
                {"type": "clock", "position": "bottom-right", "visible": True,
                 "params": {"format": "HH:MM"}},
            ]
        },
        headers=csrf_headers(api),
    )
    assert patch.status_code == 200, patch.text

    response = api.get(
        f"/api/devices/{device_id}/widgets",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data == {"weather": {}, "rss": {}}


def test_widgets_feed_weather_keyed_by_city(
    api: TestClient, enrolled_site, monkeypatch
):
    from elyon_api.services import widget_feed as wf
    from fastapi import HTTPException

    calls: list[str] = []

    def fake_feed(type: str, q=None, url=None, lat=None, lon=None):
        calls.append(type)
        if type == "weather":
            if q == "Zombie":
                raise HTTPException(status_code=404, detail="Ville introuvable")
            return {"type": "weather", "place": q, "temperature": 21.4}
        if type == "rss":
            raise HTTPException(status_code=502, detail="Flux injoignable")
        raise AssertionError(type)

    monkeypatch.setattr(wf, "widget_feed_data", fake_feed)

    _, site_id, device_id, token = enrolled_site
    screen = api.post(
        f"/api/sites/{site_id}/screens",
        json={"name": "Écran 2", "width": 1920, "height": 1080, "device_id": device_id},
        headers=csrf_headers(api),
    )
    assert screen.status_code == 201, screen.text
    patch = api.patch(
        f"/api/screens/{screen.json()['id']}",
        json={
            "widgets": [
                {"type": "weather", "position": "bottom-left", "visible": True,
                 "params": {"city": "Paris"}},
                {"type": "weather", "position": "bottom-center", "visible": True,
                 "params": {"city": "Zombie"}},
                {"type": "rss", "position": "bottom-right", "visible": True,
                 "params": {"url": "https://exemple.fr/rss.xml"}},
                {"type": "text", "position": "bottom-left", "visible": False,
                 "params": {"text": "caché"}},
            ]
        },
        headers=csrf_headers(api),
    )
    assert patch.status_code == 200, patch.text

    response = api.get(
        f"/api/devices/{device_id}/widgets",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["weather"]["Paris"] == {
        "type": "weather", "place": "Paris", "temperature": 21.4
    }
    # Widget météo en erreur : ignoré sans casser la réponse ; RSS injoignable : absent.
    assert "Zombie" not in data["weather"]
    assert data["rss"] == {}


def test_agent_refresh_widget_feed_writes_cache(agent, device_state, agent_settings, tmp_path):

    class FakeClient:
        def fetch_widgets_feed(self, state):
            return {"weather": {"Paris": {"temperature": 18}}, "rss": {}}

    refresh_widget_feed(FakeClient(), device_state, agent_settings)
    cache_file = tmp_path / "widgets-feed.json"
    assert cache_file.exists()
    cache = json.loads(cache_file.read_text(encoding="utf-8"))
    assert cache["weather"]["Paris"]["temperature"] == 18