"""Feed des widgets : prévision météo multi-jours et cache temps réel."""

from __future__ import annotations

import pytest

from elyon_api.services import widget_feed as wf

GEO_PAYLOAD = {
    "results": [
        {"latitude": 48.85, "longitude": 2.35, "name": "Paris", "country": "France"}
    ]
}
WX_PAYLOAD = {
    "current": {"temperature_2m": 21.4, "wind_speed_10m": 10.0, "weather_code": 1},
    "daily": {
        "time": ["2026-08-31", "2026-09-01", "2026-09-02"],
        "temperature_2m_max": [24.5, 22.0, 19.0],
        "temperature_2m_min": [15.2, 14.0, 13.1],
        "weather_code": [1, 61, 3],
    },
}


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _FakeClient:
    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def __enter__(self) -> _FakeClient:
        return self

    def __exit__(self, *args: object) -> bool:
        return False

    def get(self, url: str) -> _FakeResponse:
        if "geocoding" in url:
            return _FakeResponse(GEO_PAYLOAD)
        return _FakeResponse(WX_PAYLOAD)


@pytest.fixture(autouse=True)
def _clean_cache():
    wf._cache.clear()
    yield
    wf._cache.clear()


def test_fetch_weather_exposes_multi_day_forecast(monkeypatch):
    monkeypatch.setattr(wf.httpx, "Client", _FakeClient)
    data = wf.fetch_weather(q="Paris")
    assert data["place"] == "Paris, France"
    assert data["temperature"] == 21.4
    assert data["code"] == 1
    assert data["forecast"] == [
        {"date": "2026-08-31", "max": 24.5, "min": 15.2, "code": 1},
        {"date": "2026-09-01", "max": 22.0, "min": 14.0, "code": 61},
        {"date": "2026-09-02", "max": 19.0, "min": 13.1, "code": 3},
    ]


def test_fetch_weather_without_daily_returns_empty_forecast(monkeypatch):
    class _NoDaily(_FakeClient):
        def get(self, url: str) -> _FakeResponse:
            if "geocoding" in url:
                return _FakeResponse(GEO_PAYLOAD)
            return _FakeResponse({"current": {"temperature_2m": 18.0, "weather_code": 0}})

    monkeypatch.setattr(wf.httpx, "Client", _NoDaily)
    data = wf.fetch_weather(q="Paris")
    assert data["forecast"] == []
    assert data["today_max"] is None


def test_weather_cache_serves_forecast_until_ttl(monkeypatch):
    calls = {"n": 0}

    class _Counting(_FakeClient):
        def get(self, url: str) -> _FakeResponse:
            calls["n"] += 1
            return super().get(url)

    monkeypatch.setattr(wf.httpx, "Client", _Counting)
    first = wf.fetch_weather(q="Paris")
    second = wf.fetch_weather(q="Paris")
    assert second["forecast"] == first["forecast"]
    assert calls["n"] == 2  # géocodage + météo une seule fois (cache)
