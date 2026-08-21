from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from elyon_api.db import get_db
from elyon_api.deps import audit, get_current_user
from elyon_api.models import Role, User
from elyon_api.schemas import LoginRequest, UserOut
from elyon_api.security import (
    hash_password,
    new_csrf_token,
    new_session_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

_login_bucket: dict[str, list[float]] = {}


def _rate_limited(ip: str, settings) -> None:
    now = time.time()
    window = 60
    entries = [t for t in _login_bucket.get(ip, []) if now - t < window]
    _login_bucket[ip] = entries
    if len(entries) >= settings.max_login_attempts_per_minute:
        raise HTTPException(status_code=429, detail="Trop de tentatives, réessayez plus tard")


@router.post("/bootstrap", status_code=201)
def bootstrap(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> UserOut:
    count = db.scalar(select(func.count()).select_from(User))
    if count and count > 0:
        raise HTTPException(status_code=403, detail="Déjà initialisé")
    user = User(
        email=str(body.email).lower(),
        password_hash=hash_password(body.password),
        full_name="Administrateur",
        role=Role.SUPERADMIN,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    audit(db, "user.bootstrap", "user", user.id, ip=request.client.host if request.client else None)
    db.commit()
    return UserOut.model_validate(user)


@router.post("/login")
def login(
    body: LoginRequest, request: Request, response: Response, db: Session = Depends(get_db)
) -> UserOut:
    settings = request.app.state.settings
    ip = request.client.host if request.client else "unknown"
    _rate_limited(ip, settings)
    user = db.scalar(select(User).where(User.email == str(body.email).lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Identifiants invalides")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Compte désactivé")
    token = new_session_token(
        settings.session_secret, user.id, user.org_id, user.role.value, settings.session_ttl_seconds
    )
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_ttl_seconds,
        path="/",
    )
    response.set_cookie(
        settings.csrf_cookie_name,
        new_csrf_token(),
        httponly=False,
        samesite="lax",
        secure=settings.cookie_secure,
        max_age=settings.session_ttl_seconds,
        path="/",
    )
    audit(db, "auth.login", "user", user.id, user=user, ip=ip)
    db.commit()
    return UserOut.model_validate(user)


@router.post("/logout")
def logout(request: Request, response: Response) -> dict:
    settings = request.app.state.settings
    response.delete_cookie(settings.session_cookie_name, path="/")
    response.delete_cookie(settings.csrf_cookie_name, path="/")
    return {"status": "ok"}


@router.get("/me")
def me(user: User = Depends(get_current_user)) -> UserOut:
    return UserOut.model_validate(user)