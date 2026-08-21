from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from elyon_api.db import get_db
from elyon_api.models import Device, DeviceStatus, Role, User
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