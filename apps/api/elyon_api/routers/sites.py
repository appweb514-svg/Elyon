from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from elyon_api.db import get_db
from elyon_api.deps import audit, require_roles, require_site_access
from elyon_api.models import Device, Role, Screen, Site, User
from elyon_api.schemas import (
    ScreenCreate,
    ScreenOut,
    ScreenPatch,
    SiteCreate,
    SiteOut,
)

router = APIRouter(prefix="/api", tags=["sites"])

admin = require_roles(
    Role.SUPERADMIN, Role.ORG_ADMIN, Role.SITE_MANAGER, Role.OPERATOR, Role.VIEWER
)
manager = require_roles(Role.SUPERADMIN, Role.ORG_ADMIN, Role.SITE_MANAGER)


@router.get("/sites")
def list_sites(user: User = Depends(admin), db: Session = Depends(get_db)) -> list[SiteOut]:
    stmt = select(Site).order_by(Site.name)
    if user.role != Role.SUPERADMIN:
        stmt = stmt.where(Site.org_id == user.org_id)
    return [SiteOut.model_validate(s) for s in db.scalars(stmt)]


@router.post("/sites", status_code=201)
def create_site(
    body: SiteCreate,
    user: User = Depends(admin),
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
    return site


@router.get("/sites/{site_id}")
def get_site(
    site_id: str, user: User = Depends(admin), db: Session = Depends(get_db)
) -> SiteOut:
    return SiteOut.model_validate(_get_site(db, user, site_id))


@router.patch("/sites/{site_id}")
def patch_site(
    site_id: str,
    body: dict,
    user: User = Depends(admin),
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
    site_id: str, user: User = Depends(manager), db: Session = Depends(get_db)
) -> None:
    site = _get_site(db, user, site_id)
    db.delete(site)
    db.commit()
    audit(db, "site.delete", "site", site_id, user=user)
    db.commit()


@router.get("/sites/{site_id}/screens")
def list_screens(
    site_id: str, user: User = Depends(admin), db: Session = Depends(get_db)
) -> list[ScreenOut]:
    site = _get_site(db, user, site_id)
    return [
        ScreenOut.model_validate(s)
        for s in db.scalars(
            select(Screen).where(Screen.site_id == site.id).order_by(Screen.name)
        )
    ]


@router.post("/sites/{site_id}/screens", status_code=201)
def create_screen(
    site_id: str,
    body: ScreenCreate,
    user: User = Depends(manager),
    db: Session = Depends(get_db),
) -> ScreenOut:
    site = _get_site(db, user, site_id)
    if db.scalar(select(Screen).where(Screen.site_id == site.id, Screen.name == body.name)):
        raise HTTPException(status_code=409, detail="Écran déjà existant")
    if body.device_id:
        device = db.get(Device, body.device_id)
        if device is None or device.org_id != site.org_id:
            raise HTTPException(status_code=400, detail="Device invalide")
    screen = Screen(
        org_id=site.org_id,
        site_id=site.id,
        name=body.name,
        width=body.width,
        height=body.height,
        orientation=body.orientation,
        device_id=body.device_id,
    )
    db.add(screen)
    db.commit()
    db.refresh(screen)
    audit(db, "screen.create", "screen", screen.id, user=user)
    db.commit()
    return ScreenOut.model_validate(screen)


@router.patch("/screens/{screen_id}")
def patch_screen(
    screen_id: str,
    body: ScreenPatch,
    user: User = Depends(manager),
    db: Session = Depends(get_db),
) -> ScreenOut:
    screen = db.get(Screen, screen_id)
    if screen is None:
        raise HTTPException(status_code=404, detail="Écran introuvable")
    require_site_access(db, user, screen.org_id)
    data = body.model_dump(exclude_none=True)
    if "device_id" in data and data["device_id"]:
        device = db.get(Device, data["device_id"])
        if device is None or device.org_id != screen.org_id:
            raise HTTPException(status_code=400, detail="Device invalide")
    for key, value in data.items():
        setattr(screen, key, value)
    db.commit()
    db.refresh(screen)
    audit(db, "screen.update", "screen", screen.id, user=user)
    db.commit()
    return ScreenOut.model_validate(screen)


@router.delete("/screens/{screen_id}", status_code=204)
def delete_screen(
    screen_id: str, user: User = Depends(manager), db: Session = Depends(get_db)
) -> None:
    screen = db.get(Screen, screen_id)
    if screen is None:
        raise HTTPException(status_code=404, detail="Écran introuvable")
    require_site_access(db, user, screen.org_id)
    db.delete(screen)
    db.commit()
    audit(db, "screen.delete", "screen", screen_id, user=user)
    db.commit()