from __future__ import annotations

import datetime as dt
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from elyon_api.config import Settings
from elyon_api.db import get_db
from elyon_api.deps import audit, require_roles
from elyon_api.models import Device, EnrollmentToken, Organization, Role, Site, User
from elyon_api.security import hash_code, new_short_code

router = APIRouter(prefix="/api/admin/lab", tags=["lab"])

superadmin = require_roles(Role.SUPERADMIN)

TOKEN_TTL_SECONDS = 3600


def _lab_serials(settings: Settings) -> list[str]:
    return [s.strip() for s in settings.lab_player_serials.split(",") if s.strip()]


def _lab_org(db: Session, settings: Settings) -> Organization:
    org = db.scalar(select(Organization).where(Organization.slug == settings.lab_org_slug))
    if org is None:
        org = Organization(
            name="Lab", slug=settings.lab_org_slug, quota_bytes=settings.org_quota_bytes
        )
        db.add(org)
        db.commit()
        db.refresh(org)
    return org


def _lab_site(db: Session, org: Organization, settings: Settings) -> Site:
    site = db.scalar(
        select(Site).where(Site.org_id == org.id, Site.name == settings.lab_site_name)
    )
    if site is None:
        site = Site(name=settings.lab_site_name, org_id=org.id)
        db.add(site)
        db.commit()
        db.refresh(site)
    return site


def _write_code_files(settings: Settings, codes: dict[str, str]) -> list[str]:
    root = Path(settings.lab_enroll_dir)
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Impossible d'écrire dans {root} ({exc}) — vérifier le volume et les droits",
        ) from exc
    written: list[str] = []
    for serial, code in codes.items():
        path = root / f"{serial}.code"
        path.write_text(code + "\n", encoding="utf-8")
        path.chmod(0o644)
        written.append(path.name)
    return written


@router.post("/install", status_code=201)
def install(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(superadmin),
) -> dict:
    """Installe les Raspberry Pi émulés : org/site lab + code d'enrôlement
    déposé dans le volume partagé que les players émulés surveillent."""
    settings: Settings = request.app.state.settings
    serials = _lab_serials(settings)
    if not serials:
        raise HTTPException(status_code=400, detail="Aucun player lab configuré")
    org = _lab_org(db, settings)
    site = _lab_site(db, org, settings)
    now = dt.datetime.now(dt.UTC)
    expires_at = now + dt.timedelta(seconds=TOKEN_TTL_SECONDS)
    # Un code PAR player : les tokens d'enrôlement sont à usage unique.
    codes: dict[str, str] = {}
    for serial in serials:
        code = new_short_code()
        db.add(
            EnrollmentToken(
                site_id=site.id,
                code_hash=hash_code(code),
                expires_at=expires_at,
            )
        )
        codes[serial] = code
    db.commit()
    written = _write_code_files(settings, codes)
    audit(db, "lab.install", "site", site.id, user=user, detail=",".join(serials))
    db.commit()
    return {
        "org": org.slug,
        "site": site.name,
        "site_id": site.id,
        "codes": codes,
        "expires_at": expires_at.isoformat(),
        "code_files": written,
    }


@router.get("/status")
def status(
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(superadmin),
) -> dict:
    settings: Settings = request.app.state.settings
    serials = _lab_serials(settings)
    root = Path(settings.lab_enroll_dir)
    devices = {
        d.serial: d
        for d in db.scalars(select(Device).where(Device.serial.in_(serials)))
    }
    players = []
    for serial in serials:
        device = devices.get(serial)
        players.append(
            {
                "serial": serial,
                "code_file_present": (root / f"{serial}.code").is_file(),
                "enrolled": device is not None,
                "device_id": device.id if device else None,
                "device_name": device.name if device else None,
                "device_status": device.status.value if device else None,
            }
        )
    return {
        "enroll_dir": str(root),
        "enroll_dir_writable": _is_writable(root),
        "players": players,
    }


def _is_writable(root: Path) -> bool:
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False
