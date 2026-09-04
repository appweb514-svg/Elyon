"""Données des widgets d'écran (météo, RSS) — partagées back-office et player.

Appels sortants mis en cache (TTL) pour éviter de solliciter Open-Meteo ou le
flux RSS à chaque battement de cœur des players.
"""

from __future__ import annotations

import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

import httpx
from fastapi import HTTPException

CACHE_TTL_SECONDS = 600
GEO_TTL_SECONDS = 3600
WEATHER_TTL_SECONDS = 300  # prévision rafraîchie en quasi temps réel
_cache: dict[str, tuple[float, Any]] = {}


def _get_cached(key: str, ttl: int = CACHE_TTL_SECONDS) -> Any | None:
    entry = _cache.get(key)
    if entry is None or time.time() - entry[0] > ttl:
        return None
    return entry[1]


def _store(key: str, value: Any) -> None:
    _cache[key] = (time.time(), value)


def fetch_weather(
    q: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> dict[str, Any]:
    """Météo courante via Open-Meteo (gratuit, sans clé), par ville ou lat/lon."""
    place: str | None = None
    if lat is None or lon is None:
        if not q:
            raise HTTPException(status_code=400, detail="Ville ou lat/lon requis")
        cached_geo = _get_cached(geo_key(q), GEO_TTL_SECONDS)
        if cached_geo is not None:
            lat, lon, place = cached_geo
        else:
            geo_url = (
                "https://geocoding-api.open-meteo.com/v1/search"
                "?count=1&language=fr&" + urllib.parse.urlencode({"name": q})
            )
            with httpx.Client(timeout=8) as client:
                geo = client.get(geo_url).json()
            results = geo.get("results") or []
            if not results:
                raise HTTPException(status_code=404, detail="Ville introuvable")
            top = results[0]
            lat, lon = float(top["latitude"]), float(top["longitude"])
            place = f"{top.get('name')}, {top.get('country')}"
            _store(geo_key(q), (lat, lon, place))
    else:
        place = q or f"{lat:.2f},{lon:.2f}"

    wx_key = f"wx:{lat:.4f}:{lon:.4f}"
    data = _get_cached(wx_key, WEATHER_TTL_SECONDS)
    if data is not None:
        if place:
            data["place"] = place
        return data
    weather_url = (
        "https://api.open-meteo.com/v1/forecast?current=temperature_2m,"
        "weather_code,wind_speed_10m&daily=time,temperature_2m_max,"
        "temperature_2m_min,weather_code&timezone=auto&forecast_days=5&"
        + urllib.parse.urlencode({"latitude": lat, "longitude": lon})
    )
    with httpx.Client(timeout=8) as client:
        wx = client.get(weather_url).json()
    current = wx.get("current", {})
    daily = wx.get("daily", {})
    dates = daily.get("time") or []
    maxes = daily.get("temperature_2m_max") or []
    mins = daily.get("temperature_2m_min") or []
    codes = daily.get("weather_code") or []
    forecast = [
        {"date": str(d), "max": m, "min": n, "code": c}
        for d, m, n, c in zip(dates, maxes, mins, codes, strict=False)
        if d is not None
    ]
    data = {
        "type": "weather",
        "place": place,
        "temperature": current.get("temperature_2m"),
        "wind": current.get("wind_speed_10m"),
        "code": current.get("weather_code"),
        "today_max": (maxes or [None])[0],
        "today_min": (mins or [None])[0],
        "forecast": forecast,
    }
    _store(wx_key, data)
    return data


def fetch_rss(url: str) -> dict[str, Any]:
    """Derniers titres d'un flux RSS/Atom (parsing XML stdlib)."""
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) Elyon/1.0",
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:  # noqa: S310
            raw = resp.read(2_000_000)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Flux injoignable : {exc}") from exc
    titles: list[str] = []
    try:
        root = ET.fromstring(raw)
        for item in root.iter():
            tag = item.tag.rsplit("}", 1)[-1]
            if tag in ("item", "entry"):
                for child in item:
                    if child.tag.rsplit("}", 1)[-1] == "title":
                        text = "".join(child.itertext()).strip()
                        if text:
                            titles.append(text)
                        break
    except ET.ParseError as exc:
        raise HTTPException(status_code=502, detail="Flux XML invalide") from exc
    return {"type": "rss", "url": url, "items": titles[:10]}


def geo_key(q: str) -> str:
    return f"geo:{q.strip().lower()}"


def wx_key(lat: float, lon: float) -> str:
    return f"wx:{lat:.4f}:{lon:.4f}"


def rss_key(url: str) -> str:
    return f"rss:{url}"


def cached_geo(q: str) -> tuple[float, float, str] | None:
    value = _get_cached(geo_key(q), GEO_TTL_SECONDS)
    if value is None:
        return None
    lat, lon, place = value
    return float(lat), float(lon), str(place)


def cached_weather(lat: float, lon: float) -> dict[str, Any] | None:
    value = _get_cached(wx_key(lat, lon), WEATHER_TTL_SECONDS)
    return dict(value) if isinstance(value, dict) else None


def cached_rss(url: str) -> dict[str, Any] | None:
    value = _get_cached(rss_key(url))
    return dict(value) if isinstance(value, dict) else None


def widget_feed_data(
    type: str,
    q: str | None = None,
    url: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
) -> dict[str, Any]:
    """Point d'entrée unique : données d'un widget (back-office + player)."""
    if type == "weather":
        if lat is None or lon is None:
            if not q:
                raise HTTPException(status_code=400, detail="Ville ou lat/lon requis")
            cached_place = cached_geo(q)
            if cached_place is not None:
                lat, lon, place = cached_place
                cached_wx = cached_weather(lat, lon)
                if cached_wx is not None:
                    cached_wx["place"] = place
                    return cached_wx
        return fetch_weather(q=q, lat=lat, lon=lon)
    if type == "rss":
        if not url:
            raise HTTPException(status_code=400, detail="URL du flux requise")
        cached = cached_rss(url)
        if cached is not None:
            return cached
        return fetch_rss(url)
    raise HTTPException(status_code=400, detail="Type de widget inconnu")
