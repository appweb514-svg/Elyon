from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from elyon_api.db import get_db
from elyon_api.deps import audit, require_permission, require_roles, require_site_access
from elyon_api.models import Device, Role, Screen, Site, User
from elyon_api.permissions import Permission
from elyon_api.schemas import (
    ScreenCreate,
    ScreenLayout,
    ScreenOut,
    ScreenPatch,
    SiteCreate,
    SiteOut,
    WidgetOut,
)

router = APIRouter(prefix="/api", tags=["sites"])

admin = require_roles(
    Role.SUPERADMIN, Role.ORG_ADMIN, Role.SITE_MANAGER, Role.OPERATOR, Role.VIEWER
)
manager = require_roles(Role.SUPERADMIN, Role.ORG_ADMIN, Role.SITE_MANAGER)


@router.get("/sites")
def list_sites(
    user: User = Depends(require_permission(Permission.SCREEN_VIEW)),
    db: Session = Depends(get_db),
) -> list[SiteOut]:
    stmt = select(Site).order_by(Site.name)
    if user.role != Role.SUPERADMIN:
        stmt = stmt.where(Site.org_id == user.org_id)
    if user.site_id is not None:
        stmt = stmt.where(Site.id == user.site_id)
    return [SiteOut.model_validate(s) for s in db.scalars(stmt)]


@router.post("/sites", status_code=201)
def create_site(
    body: SiteCreate,
    user: User = Depends(require_permission(Permission.SCREEN_CREATE)),
    db: Session = Depends(get_db),
) -> SiteOut:
    if user.role == Role.SUPERADMIN:
        raise HTTPException(status_code=400, detail="org_id requis pour un superadmin")
    if db.scalar(select(Site).where(Site.org_id == user.org_id, Site.name == body.name)):
        raise HTTPException(status_code=409, detail="Site déjà existant")
    site = Site(org_id=user.org_id, name=body.name, timezone=body.timezone, address=body.address)
    db.add(site)
    db.commit()
    db.refresh(site)
    audit(db, "site.create", "site", site.id, user=user)
    db.commit()
    return SiteOut.model_validate(site)


def _get_site(db: Session, user: User, site_id: str) -> Site:
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site introuvable")
    require_site_access(db, user, site.org_id)
    if user.site_id is not None and site.id != user.site_id:
        raise HTTPException(status_code=403, detail="Hors périmètre site")
    return site


def _screen_to_out(screen: Screen) -> ScreenOut:
    out = ScreenOut.model_validate(screen)
    import json as _json

    if screen.layout_json:
        try:
            out.layout = ScreenLayout.model_validate(_json.loads(screen.layout_json))
        except Exception:
            out.layout = None
    if screen.widgets_json:
        try:
            out.widgets = [
                WidgetOut.model_validate(w) for w in _json.loads(screen.widgets_json)
            ]
        except Exception:
            out.widgets = None
    return out


@router.get("/sites/{site_id}")
def get_site(
    site_id: str,
    user: User = Depends(require_permission(Permission.SCREEN_VIEW)),
    db: Session = Depends(get_db),
) -> SiteOut:
    return SiteOut.model_validate(_get_site(db, user, site_id))


@router.patch("/sites/{site_id}")
def patch_site(
    site_id: str,
    body: dict,
    user: User = Depends(require_permission(Permission.SCREEN_EDIT)),
    db: Session = Depends(get_db),
) -> SiteOut:
    site = _get_site(db, user, site_id)
    for key in ("name", "timezone", "address"):
        if key in body:
            setattr(site, key, body[key])
    db.commit()
    db.refresh(site)
    audit(db, "site.update", "site", site.id, user=user)
    db.commit()
    return SiteOut.model_validate(site)


@router.delete("/sites/{site_id}", status_code=204)
def delete_site(
    site_id: str,
    user: User = Depends(require_permission(Permission.SCREEN_DELETE)),
    db: Session = Depends(get_db),
) -> None:
    site = _get_site(db, user, site_id)
    db.delete(site)
    db.commit()
    audit(db, "site.delete", "site", site_id, user=user)
    db.commit()


@router.get("/sites/{site_id}/screens")
def list_screens(
    site_id: str,
    user: User = Depends(require_permission(Permission.SCREEN_VIEW)),
    db: Session = Depends(get_db),
) -> list[ScreenOut]:
    site = _get_site(db, user, site_id)
    return [_screen_to_out(s) for s in db.scalars(
        select(Screen).where(Screen.site_id == site.id).order_by(Screen.name)
    )]


@router.post("/sites/{site_id}/screens", status_code=201)
def create_screen(
    site_id: str,
    body: ScreenCreate,
    user: User = Depends(require_permission(Permission.SCREEN_CREATE)),
    db: Session = Depends(get_db),
) -> ScreenOut:
    site = _get_site(db, user, site_id)
    if db.scalar(select(Screen).where(Screen.site_id == site.id, Screen.name == body.name)):
        raise HTTPException(status_code=409, detail="Écran déjà existant")
    if body.device_id:
        from elyon_api.permissions import Permission as _Perm
        from elyon_api.permissions import has_permission as _has_perm

        if not _has_perm(user.role, _Perm.SCREEN_ASSIGN):
            raise HTTPException(status_code=403, detail="Permission manquante")
        device = db.get(Device, body.device_id)
        if device is None or device.org_id != site.org_id:
            raise HTTPException(status_code=400, detail="Device invalide")
    import json as _json

    screen = Screen(
        org_id=site.org_id,
        site_id=site.id,
        name=body.name,
        width=body.width,
        height=body.height,
        orientation=body.orientation,
        device_id=body.device_id,
        layout_json=_json.dumps(body.layout.model_dump()) if body.layout else None,
    )
    db.add(screen)
    db.commit()
    db.refresh(screen)
    audit(db, "screen.create", "screen", screen.id, user=user)
    db.commit()
    return _screen_to_out(screen)


@router.patch("/screens/{screen_id}")
def patch_screen(
    screen_id: str,
    body: ScreenPatch,
    user: User = Depends(require_permission(Permission.SCREEN_EDIT)),
    db: Session = Depends(get_db),
) -> ScreenOut:
    screen = db.get(Screen, screen_id)
    if screen is None:
        raise HTTPException(status_code=404, detail="Écran introuvable")
    require_site_access(db, user, screen.org_id)
    if user.site_id is not None and screen.site_id != user.site_id:
        raise HTTPException(status_code=403, detail="Hors périmètre site")
    data = body.model_dump(exclude_none=True)
    if "device_id" in data and data["device_id"]:
        device = db.get(Device, data["device_id"])
        if device is None or device.org_id != screen.org_id:
            raise HTTPException(status_code=400, detail="Device invalide")
    # layout → layout_json
    if "layout" in data:
        import json as _json

        layout_val = data.pop("layout")
        if layout_val is not None:
            raw = layout_val if isinstance(layout_val, dict) else layout_val
            screen.layout_json = _json.dumps(raw)
        else:
            screen.layout_json = None
    # widgets → widgets_json
    if "widgets" in data:
        import json as _json

        widgets_val = data.pop("widgets")
        if widgets_val is not None:
            screen.widgets_json = _json.dumps(widgets_val)
        else:
            screen.widgets_json = None
    if "device_id" in data and data["device_id"] is not None:
        # screen.assign permission for device assignment
        from elyon_api.permissions import Permission as _Perm
        from elyon_api.permissions import has_permission as _has_perm

        if not _has_perm(user.role, _Perm.SCREEN_ASSIGN):
            raise HTTPException(status_code=403, detail="Permission manquante")
    for key, value in data.items():
        setattr(screen, key, value)
    db.commit()
    db.refresh(screen)
    audit(db, "screen.update", "screen", screen.id, user=user)
    db.commit()
    return _screen_to_out(screen)


@router.delete("/screens/{screen_id}", status_code=204)
def delete_screen(
    screen_id: str,
    user: User = Depends(require_permission(Permission.SCREEN_DELETE)),
    db: Session = Depends(get_db),
) -> None:
    screen = db.get(Screen, screen_id)
    if screen is None:
        raise HTTPException(status_code=404, detail="Écran introuvable")
    require_site_access(db, user, screen.org_id)
    db.delete(screen)
    db.commit()
    audit(db, "screen.delete", "screen", screen_id, user=user)
    db.commit()

@router.get("/widgets/feed")
def widget_feed(
    type: str,
    q: str | None = None,
    url: str | None = None,
    lat: float | None = None,
    lon: float | None = None,
    user: User = Depends(require_permission(Permission.SCREEN_VIEW)),
) -> dict:
    """Données pour les widgets d'écran (aperçu back-office + player).

    - Météo : Open-Meteo (gratuit, sans clé) via nom de ville ou lat/lon ;
    - RSS : les derniers titres d'un flux (parsing XML stdlib).
    """
    from elyon_api.services.widget_feed import widget_feed_data

    return widget_feed_data(type=type, q=q, url=url, lat=lat, lon=lon)
