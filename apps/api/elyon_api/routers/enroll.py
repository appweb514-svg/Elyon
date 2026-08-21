from __future__ import annotations

import datetime as dt
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from elyon_api.db import get_db
from elyon_api.deps import (
    audit,
    get_device_from_request,
    require_permission,
    require_roles,
    require_site_access,
)
from elyon_api.models import (
    Device,
    DeviceStatus,
    EnrollmentToken,
    Event,
    EventLevel,
    Role,
    Site,
    User,
)
from elyon_api.permissions import Permission
from elyon_api.schemas import (
    DeviceOut,
    DevicePatch,
    EnrollRequest,
    EnrollResponse,
    EnrollTokenOut,
)
from elyon_api.security import hash_code, hash_token, new_short_code

router = APIRouter(prefix="/api", tags=["enroll"])

admin = require_roles(
    Role.SUPERADMIN, Role.ORG_ADMIN, Role.SITE_MANAGER, Role.OPERATOR, Role.VIEWER
)


def _get_site(db: Session, user: User, site_id: str) -> Site:
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site introuvable")
    require_site_access(db, user, site.org_id)
    return site


@router.post("/enroll/tokens", status_code=201)
def create_enroll_token(
    site_id: str,
    ttl_seconds: int = 600,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
) -> EnrollTokenOut:
    site = _get_site(db, user, site_id)
    code = new_short_code()
    token = EnrollmentToken(
        site_id=site.id,
        code_hash=hash_code(code),
        expires_at=dt.datetime.now(dt.UTC) + dt.timedelta(seconds=ttl_seconds),
    )
    db.add(token)
    db.commit()
    db.refresh(token)
    audit(db, "enroll.token_create", "enrollment_token", token.id, user=user)
    db.commit()
    return EnrollTokenOut(id=token.id, site_id=site.id, code=code, expires_at=token.expires_at)


@router.post("/enroll/request", status_code=201)
def enroll_request(
    body: EnrollRequest, db: Session = Depends(get_db)
) -> EnrollResponse:
    now = dt.datetime.now(dt.UTC)
    token = db.scalar(
        select(EnrollmentToken).where(
            EnrollmentToken.code_hash == hash_code(body.site_code.upper()),
            EnrollmentToken.expires_at > now,
            EnrollmentToken.used_at.is_(None),
        )
    )
    if token is None:
        raise HTTPException(status_code=401, detail="Code d'enrôlement invalide ou expiré")
    if db.scalar(select(Device).where(Device.serial == body.serial)):
        raise HTTPException(status_code=409, detail="Série déjà enrôlée")
    site = db.get(Site, token.site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site introuvable")
    raw_token = secrets.token_urlsafe(32)
    device = Device(
        org_id=site.org_id,
        site_id=site.id,
        name=body.name,
        serial=body.serial,
        status=DeviceStatus.PENDING,
        public_key=body.public_key,
        auth_token_hash=hash_token(raw_token),
        auth_token_created_at=now,
    )
    db.add(device)
    token.used_at = now
    db.commit()
    db.refresh(device)
    return EnrollResponse(device_id=device.id, token=raw_token)


@router.get("/devices")
def list_devices(
    site_id: str | None = None,
    status: DeviceStatus | None = None,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
) -> list[DeviceOut]:
    import datetime as _dt

    from elyon_api.deps import compute_device_status

    now = _dt.datetime.now(_dt.UTC)
    stmt = select(Device).order_by(Device.created_at.desc())
    if user.role != Role.SUPERADMIN:
        stmt = stmt.where(Device.org_id == user.org_id)
    if site_id:
        stmt = stmt.where(Device.site_id == site_id)
    if status:
        stmt = stmt.where(Device.status == status)
    devices = db.scalars(stmt)
    result = []
    for device in devices:
        out = DeviceOut.model_validate(device)
        out.screen_id = device.screen.id if device.screen else None
        try:
            out.computed_status = compute_device_status(device, now, 90)
        except Exception:
            out.computed_status = device.status.value
        result.append(out)
    return result


@router.get("/devices/{device_id}")
def get_device(
    device_id: str, user: User = Depends(admin), db: Session = Depends(get_db)
) -> DeviceOut:
    import datetime as _dt

    from elyon_api.deps import compute_device_status

    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device introuvable")
    require_site_access(db, user, device.org_id)
    out = DeviceOut.model_validate(device)
    out.screen_id = device.screen.id if device.screen else None
    try:
        out.computed_status = compute_device_status(
            device, _dt.datetime.now(_dt.UTC), 90
        )
    except Exception:
        out.computed_status = device.status.value
    return out


@router.patch("/devices/{device_id}")
def patch_device(
    device_id: str,
    body: DevicePatch,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
) -> DeviceOut:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device introuvable")
    require_site_access(db, user, device.org_id)
    if body.name is not None:
        device.name = body.name
    if body.site_id is not None:
        site = _get_site(db, user, body.site_id)
        device.site_id = site.id
    db.commit()
    db.refresh(device)
    audit(db, "device.update", "device", device.id, user=user)
    db.commit()
    out = DeviceOut.model_validate(device)
    out.screen_id = device.screen.id if device.screen else None
    return out


@router.post("/devices/{device_id}/approve")
def approve_device(
    device_id: str, user: User = Depends(require_permission(Permission.DEVICE_APPROVE)),  # noqa: E501
    db: Session = Depends(get_db)
) -> DeviceOut:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device introuvable")
    require_site_access(db, user, device.org_id)
    if device.status not in (
        DeviceStatus.PENDING, DeviceStatus.DISABLED, DeviceStatus.MAINTENANCE
    ):
        raise HTTPException(status_code=409, detail="Device non en attente")
    device.status = DeviceStatus.APPROVED
    db.commit()
    db.refresh(device)
    audit(db, "device.approve", "device", device.id, user=user)
    _event(db, device.org_id, device.site_id, device.id, "device_approved", EventLevel.INFO,
           f"Player {device.name} approuvé")
    db.commit()
    out = DeviceOut.model_validate(device)
    out.screen_id = device.screen.id if device.screen else None
    return out


@router.post("/devices/{device_id}/block")
def block_device(
    device_id: str, user: User = Depends(require_permission(Permission.DEVICE_DISABLE)),  # noqa: E501
    db: Session = Depends(get_db)
) -> DeviceOut:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device introuvable")
    require_site_access(db, user, device.org_id)
    device.status = DeviceStatus.BLOCKED
    device.auth_token_revoked_at = dt.datetime.now(dt.UTC)
    if device.screen:
        device.screen.device_id = None
    db.commit()
    db.refresh(device)
    audit(db, "device.block", "device", device.id, user=user)
    _event(db, device.org_id, device.site_id, device.id, "device_blocked", EventLevel.WARNING,
           f"Player {device.name} révoqué")
    db.commit()
    out = DeviceOut.model_validate(device)
    out.screen_id = None
    return out


@router.post("/devices/{device_id}/disable")
def disable_device(
    device_id: str, user: User = Depends(require_permission(Permission.DEVICE_DISABLE)),  # noqa: E501
    db: Session = Depends(get_db)
) -> DeviceOut:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device introuvable")
    require_site_access(db, user, device.org_id)
    if device.status == DeviceStatus.BLOCKED:
        raise HTTPException(status_code=409, detail="Device bloqué — réapprouver d'abord")
    device.status = DeviceStatus.DISABLED
    db.commit()
    db.refresh(device)
    audit(db, "device.disable", "device", device.id, user=user)
    _event(
        db, device.org_id, device.site_id, device.id,
        "device_disabled", EventLevel.WARNING, f"Player {device.name} désactivé"
    )
    db.commit()
    out = DeviceOut.model_validate(device)
    out.screen_id = device.screen.id if device.screen else None
    return out


@router.post("/devices/{device_id}/maintenance")
def maintenance_device(
    device_id: str, user: User = Depends(require_permission(Permission.DEVICE_DISABLE)),  # noqa: E501
    db: Session = Depends(get_db)
) -> DeviceOut:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device introuvable")
    require_site_access(db, user, device.org_id)
    device.status = DeviceStatus.MAINTENANCE
    db.commit()
    db.refresh(device)
    audit(db, "device.maintenance", "device", device.id, user=user)
    db.commit()
    out = DeviceOut.model_validate(device)
    out.screen_id = device.screen.id if device.screen else None
    return out


@router.post("/devices/{device_id}/enable")
def enable_device(
    device_id: str, user: User = Depends(require_permission(Permission.DEVICE_APPROVE)),  # noqa: E501
    db: Session = Depends(get_db)
) -> DeviceOut:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device introuvable")
    require_site_access(db, user, device.org_id)
    if device.status not in (DeviceStatus.DISABLED, DeviceStatus.MAINTENANCE):
        raise HTTPException(status_code=409, detail="Device non désactivé")
    device.status = DeviceStatus.APPROVED
    db.commit()
    db.refresh(device)
    audit(db, "device.enable", "device", device.id, user=user)
    db.commit()
    out = DeviceOut.model_validate(device)
    out.screen_id = device.screen.id if device.screen else None
    return out


@router.post("/devices/{device_id}/rotate-token")
def rotate_token(
    device_id: str,
    user: User = Depends(require_permission(Permission.DEVICE_UPDATE)),  # noqa: E501
    db: Session = Depends(get_db)
) -> dict:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device introuvable")
    require_site_access(db, user, device.org_id)
    raw_token = secrets.token_urlsafe(32)
    now = dt.datetime.now(dt.UTC)
    device.auth_token_hash = hash_token(raw_token)
    device.auth_token_created_at = now
    device.auth_token_revoked_at = None
    db.commit()
    audit(db, "device.rotate_token", "device", device.id, user=user)
    db.commit()
    return {"device_id": device.id, "token": raw_token}


@router.get("/devices/{device_id}/heartbeat")
def heartbeat(
    device: Device = Depends(get_device_from_request),
    db: Session = Depends(get_db),
) -> dict:
    return {
        "status": "ok",
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
    }


def _event(db: Session, org_id: str, site_id: str | None, device_id: str | None,
           type_: str, level: EventLevel, message: str, detail: str | None = None) -> None:
    db.add(Event(org_id=org_id, site_id=site_id, device_id=device_id, type=type_,
                 level=level, message=message, detail=detail))