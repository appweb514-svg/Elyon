from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from elyon_api.db import get_db
from elyon_api.deps import audit, get_device_from_request, require_permission, require_site_access
from elyon_api.models import Device, User
from elyon_api.permissions import Permission
from elyon_api.schemas import ManifestOut
from elyon_api.services.manifest import latest_manifest, publish_manifest

router = APIRouter(prefix="/api", tags=["publish"])


def _get_device(db: Session, user: User, device_id: str) -> Device:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device introuvable")
    require_site_access(db, user, device.org_id)
    return device


@router.post("/devices/{device_id}/publish")
def publish(
    device_id: str,
    request: Request,
    user: User = Depends(require_permission(Permission.SCHEDULE_PUBLISH)),
    db: Session = Depends(get_db),
) -> ManifestOut:
    device = _get_device(db, user, device_id)
    manifest = publish_manifest(db, device, request.app.state.settings)
    audit(db, "manifest.publish", "device", device.id, detail=f"v{manifest.version}", user=user)
    db.commit()
    return ManifestOut.model_validate(manifest)


@router.get("/devices/{device_id}/manifest")
def fetch_manifest(
    device_id: str,
    request: Request,
    device: Device = Depends(get_device_from_request),
    db: Session = Depends(get_db),
) -> ManifestOut:
    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Accès refusé")
    if device.is_preview:
        from elyon_api.services.manifest import live_preview_manifest

        live = live_preview_manifest(db, device, request.app.state.settings)
        return ManifestOut(
            version=live.version,
            payload=live.payload,
            signature=live.signature,
            published_at=live.published_at,
        )
    manifest = latest_manifest(db, device_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Aucun manifeste publié")
    return ManifestOut.model_validate(manifest)


@router.get("/devices/{device_id}/widgets")
def device_widget_feed(
    device_id: str,
    device: Device = Depends(get_device_from_request),
    db: Session = Depends(get_db),
) -> dict:
    """Données des widgets de l'écran associé, pour le rendu côté player.

    Clé par type+paramètre : {"weather": {"<ville>": {...}}, "rss": {"<url>": {...}}}.
    Les types text/clock/html sont rendus localement par le player (pas d'appel).
    """
    from sqlalchemy import select

    from elyon_api.models import Screen
    from elyon_api.services.widget_feed import widget_feed_data

    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Accès refusé")
    weather: dict[str, dict] = {}
    rss: dict[str, dict] = {}
    screen = device.screen
    if screen is None and device_id:
        # Compat : écran rattaché côté Screen.device_id sans relation chargée.
        screen = db.scalar(select(Screen).where(Screen.device_id == device.id))
    if screen is not None and screen.widgets_json:
        try:
            widgets = json.loads(screen.widgets_json)
        except Exception:  # noqa: BLE001
            widgets = []
        for widget in widgets if isinstance(widgets, list) else []:
            if not isinstance(widget, dict) or not widget.get("visible", True):
                continue
            params = widget.get("params") or {}
            if widget.get("type") == "weather":
                city = str(params.get("city") or "").strip()
                if city and city not in weather:
                    try:
                        weather[city] = widget_feed_data(type="weather", q=city)
                    except HTTPException:
                        continue
            elif widget.get("type") == "rss":
                url = str(params.get("url") or "").strip()
                if url and url not in rss:
                    try:
                        rss[url] = widget_feed_data(type="rss", url=url)
                    except HTTPException:
                        continue
    return {"weather": weather, "rss": rss}