from __future__ import annotations

import datetime as dt
import secrets
import time

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from elyon_api.db import get_db
from elyon_api.deps import (
    audit,
    require_permission,
    require_site_access,
    require_site_id_access,
)
from elyon_api.models import (
    Device,
    DeviceStatus,
    EnrollmentToken,
    Event,
    EventLevel,
    Role,
    Screen,
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

# Limitation de débit de l'enrôlement par IP : sans elle, un code court
# (6 caractères hexadécimaux) pouvait être brute-forcé.
_enroll_attempts: dict[str, list[float]] = {}
_ENROLL_WINDOW_SECONDS = 60


def _enroll_rate_limited(ip: str, settings) -> None:
    now = time.time()
    for key in list(_enroll_attempts):
        recent = [t for t in _enroll_attempts[key] if now - t < _ENROLL_WINDOW_SECONDS]
        if recent:
            _enroll_attempts[key] = recent
        else:
            del _enroll_attempts[key]
    attempts = _enroll_attempts.setdefault(ip, [])
    attempts.append(now)
    if len(attempts) > settings.max_enroll_attempts_per_minute:
        raise HTTPException(status_code=429, detail="Trop de tentatives d'enrôlement")


def _get_site(db: Session, user: User, site_id: str) -> Site:
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site introuvable")
    require_site_access(db, user, site.org_id)
    require_site_id_access(user, site.id)
    return site


@router.post("/enroll/tokens", status_code=201)
def create_enroll_token(
    site_id: str,
    ttl_seconds: int = 600,
    user: User = Depends(require_permission(Permission.DEVICE_APPROVE)),
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
    body: EnrollRequest, request: Request, db: Session = Depends(get_db)
) -> EnrollResponse:
    settings = request.app.state.settings
    ip = request.client.host if request.client else "unknown"
    _enroll_rate_limited(ip, settings)
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
    response: Response,
    site_id: str | None = None,
    status: DeviceStatus | None = None,
    limit: int | None = Query(default=None, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(require_permission(Permission.DEVICE_VIEW)),
    db: Session = Depends(get_db),
) -> list[DeviceOut]:
    import datetime as _dt

    from elyon_api.deps import compute_device_status

    now = _dt.datetime.now(_dt.UTC)
    stmt = select(Device).order_by(Device.created_at.desc())
    if user.role != Role.SUPERADMIN:
        stmt = stmt.where(Device.org_id == user.org_id)
    if user.site_id is not None:
        stmt = stmt.where(Device.site_id == user.site_id)
    if site_id:
        stmt = stmt.where(Device.site_id == site_id)
    if status:
        stmt = stmt.where(Device.status == status)
    from sqlalchemy import func as _func

    total = db.scalar(select(_func.count()).select_from(stmt.subquery())) or 0
    response.headers["X-Total-Count"] = str(total)
    if limit is not None:
        stmt = stmt.limit(limit).offset(offset)
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
    device_id: str,
    user: User = Depends(require_permission(Permission.DEVICE_VIEW)),
    db: Session = Depends(get_db),
) -> DeviceOut:
    import datetime as _dt

    from elyon_api.deps import compute_device_status

    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device introuvable")
    require_site_access(db, user, device.org_id)
    require_site_id_access(user, device.site_id)
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
    user: User = Depends(require_permission(Permission.DEVICE_UPDATE)),
    db: Session = Depends(get_db),
) -> DeviceOut:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device introuvable")
    require_site_access(db, user, device.org_id)
    require_site_id_access(user, device.site_id)
    if body.name is not None:
        device.name = body.name
    if body.site_id is not None:
        site = _get_site(db, user, body.site_id)
        device.site_id = site.id
    if body.is_preview is not None:
        device.is_preview = body.is_preview
    if body.screen_id is not None:
        # Dissocier l'ancien écran du device, associer le nouveau.
        for other in db.scalars(select(Screen).where(Screen.device_id == device.id)):
            other.device_id = None
        if body.screen_id:
            screen = db.get(Screen, body.screen_id)
            if screen is None or screen.org_id != device.org_id:
                raise HTTPException(status_code=400, detail="Écran invalide")
            screen.device_id = device.id
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
    require_site_id_access(user, device.site_id)
    if device.status not in (
        DeviceStatus.PENDING, DeviceStatus.DISABLED, DeviceStatus.MAINTENANCE
    ):
        raise HTTPException(status_code=409, detail="Device non en attente")
    device.status = DeviceStatus.APPROVED
    db.commit()
    db.refresh(device)
    audit(db, "device.approve", "device", device.id, user=user)
    _event(db, device.org_id, device.site_id, device.id, "device_approved", EventLevel.INFO,
           f"Appareil {device.name} approuvé")
    db.commit()
    out = DeviceOut.model_validate(device)
    out.screen_id = device.screen.id if device.screen else None
    return out


@router.post("/devices/{device_id}/unblock")
def unblock_device(
    device_id: str, user: User = Depends(require_permission(Permission.DEVICE_APPROVE)),  # noqa: E501
    db: Session = Depends(get_db)
) -> DeviceOut:
    """Réactive un device bloqué : nouveau token requis (l'ancien est révoqué).

    Le device repasse en « pending » : il doit se réenrôler sur place avec un
    nouveau code (rotation de token), puis être approuvé — même parcours qu'un
    matériel récupéré après perte.
    """
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device introuvable")
    require_site_access(db, user, device.org_id)
    require_site_id_access(user, device.site_id)
    if device.status != DeviceStatus.BLOCKED:
        raise HTTPException(status_code=409, detail="Device non bloqué")
    device.status = DeviceStatus.PENDING
    db.commit()
    db.refresh(device)
    audit(db, "device.unblock", "device", device.id, user=user)
    _event(db, device.org_id, device.site_id, device.id, "device_unblocked", EventLevel.INFO,
           f"Appareil {device.name} débloqué — réenrôlement requis")
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
    require_site_id_access(user, device.site_id)
    device.status = DeviceStatus.BLOCKED
    device.auth_token_revoked_at = dt.datetime.now(dt.UTC)
    if device.screen:
        device.screen.device_id = None
    db.commit()
    db.refresh(device)
    audit(db, "device.block", "device", device.id, user=user)
    _event(db, device.org_id, device.site_id, device.id, "device_blocked", EventLevel.WARNING,
           f"Appareil {device.name} révoqué")
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
    require_site_id_access(user, device.site_id)
    if device.status == DeviceStatus.BLOCKED:
        raise HTTPException(status_code=409, detail="Device bloqué — réapprouver d'abord")
    device.status = DeviceStatus.DISABLED
    db.commit()
    db.refresh(device)
    audit(db, "device.disable", "device", device.id, user=user)
    _event(
        db, device.org_id, device.site_id, device.id,
        "device_disabled", EventLevel.WARNING, f"Appareil {device.name} désactivé"
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
    require_site_id_access(user, device.site_id)
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
    require_site_id_access(user, device.site_id)
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
    require_site_id_access(user, device.site_id)
    raw_token = secrets.token_urlsafe(32)
    now = dt.datetime.now(dt.UTC)
    device.auth_token_hash = hash_token(raw_token)
    device.auth_token_created_at = now
    device.auth_token_revoked_at = None
    db.commit()
    audit(db, "device.rotate_token", "device", device.id, user=user)
    db.commit()
    return {"device_id": device.id, "token": raw_token}


def _event(db: Session, org_id: str, site_id: str | None, device_id: str | None,
           type_: str, level: EventLevel, message: str, detail: str | None = None) -> None:
    db.add(Event(org_id=org_id, site_id=site_id, device_id=device_id, type=type_,
                 level=level, message=message, detail=detail))