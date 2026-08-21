from __future__ import annotations

import datetime as dt
import json
from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from elyon_api.db import get_db
from elyon_api.models import Device, DeviceStatus, Role, User, ensure_utc
from elyon_api.permissions import Permission, has_permission
from elyon_api.security import hash_token, verify_session_token


def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get(request.app.state.settings.session_cookie_name)
    if not token:
        raise HTTPException(status_code=401, detail="Authentification requise")
    payload = verify_session_token(request.app.state.settings.session_secret, token)
    if not payload:
        raise HTTPException(status_code=401, detail="Session invalide")
    user = db.get(User, payload["uid"])
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="Compte inactif")
    return user


def require_roles(*roles: Role) -> Callable[[User], User]:
    def checker(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status_code=403, detail="Accès refusé")
        return user

    return checker


def require_same_org(db: Session, user: User, org_id: str | None) -> None:
    if user.role == Role.SUPERADMIN:
        return
    if org_id is None or org_id != user.org_id:
        raise HTTPException(status_code=403, detail="Hors périmètre organisation")


def require_site_access(db: Session, user: User, site_org_id: str | None) -> None:
    if user.role == Role.SUPERADMIN:
        return
    if site_org_id is None or site_org_id != user.org_id:
        raise HTTPException(status_code=403, detail="Hors périmètre site")
    # SITE_MANAGER/OPERATOR/VIEWER scopés à un site précis si user.site_id renseigné
    if user.site_id is not None:
        # Le site doit appartenir à l'org déjà vérifié ; on vérifie que le user
        # n'accède qu'à son site. Le caller passe site_org_id = site.org_id, pas site.id ;
        # on ne peut pas vérifier site.id ici sans paramètre supplémentaire —
        # la vérification fine se fait dans les routers via require_site_id_access.
        pass


def require_site_id_access(user: User, site_id: str) -> None:
    """Vérifie que l'utilisateur scopé site n'accède qu'à son site."""
    if user.role == Role.SUPERADMIN:
        return
    if user.site_id is not None and user.site_id != site_id:
        raise HTTPException(status_code=403, detail="Hors périmètre site")


def require_permission(perm: Permission):  # type: ignore[no-untyped-def]
    def checker(user: User = Depends(get_current_user)) -> User:
        if not has_permission(user.role, perm):
            raise HTTPException(status_code=403, detail="Permission manquante")
        return user

    return checker


def get_device_from_request(request: Request, db: Session = Depends(get_db)) -> Device:
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Token device manquant")
    token = auth.removeprefix("Bearer ").strip()
    device = db.scalar(
        select(Device).where(
            Device.auth_token_hash == hash_token(token),
            Device.auth_token_revoked_at.is_(None),
        )
    )
    if device is None:
        raise HTTPException(status_code=401, detail="Token device invalide")
    if device.status != DeviceStatus.APPROVED:
        raise HTTPException(status_code=403, detail="Device non approuvé")
    return device


def compute_device_status(
    device: Device,
    now: dt.datetime,
    grace_seconds: int,
    manifest: object = None,
    current_media_id: str | None = None,
) -> str:
    """Statut dérivé : pending/approved/disabled/maintenance + online/offline/syncing."""
    if device.status == DeviceStatus.PENDING:
        return "pending"
    if device.status in (DeviceStatus.BLOCKED, DeviceStatus.DISABLED):
        return device.status.value
    if device.status == DeviceStatus.MAINTENANCE:
        return "maintenance"
    # APPROVED / SYNCING → online/offline/syncing selon heartbeat et manifeste
    if device.status == DeviceStatus.SYNCING:
        return "syncing"
    # approved → online/offline
    last = getattr(device, "last_seen_at", None)
    if last is None:
        return "offline"
    try:
        last_utc = ensure_utc(last)  # type: ignore[arg-type]
        delta = (now - last_utc).total_seconds()
    except Exception:
        return "offline"
    if delta > grace_seconds:
        return "offline"
    return "online"


def audit(
    db: Session,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    detail: str | None = None,
    user: User | None = None,
    org_id: str | None = None,
    ip: str | None = None,
) -> None:
    from elyon_api.models import AuditLog

    db.add(
        AuditLog(
            org_id=org_id if org_id is not None else (user.org_id if user else None),
            user_id=user.id if user else None,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            detail=detail,
            ip=ip,
        )
    )


def detail_json(value: dict[str, Any] | list[Any]) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)