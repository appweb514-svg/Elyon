from __future__ import annotations

import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from elyon_api.db import get_db
from elyon_api.deps import audit, get_current_user
from elyon_api.models import Role, User
from elyon_api.schemas import LoginRequest, ProfilePatch, UserOut
from elyon_api.security import (
    hash_password,
    new_csrf_token,
    new_session_token,
    verify_password,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

_login_failures: dict[str, list[float]] = {}

_LOGIN_WINDOW_SECONDS = 60


def _prune_login_failures(now: float) -> None:
    """Purge les entrées expirées (évite que le seau ne grossisse sans fin)."""
    for ip in list(_login_failures):
        entries = [t for t in _login_failures[ip] if now - t < _LOGIN_WINDOW_SECONDS]
        if entries:
            _login_failures[ip] = entries
        else:
            del _login_failures[ip]


def _rate_limit_check(ip: str, settings) -> None:
    """Refuse la tentative si le quota d'échecs récents est atteint.

    Seuls les échecs comptent : un utilisateur légitime derrière un NAT ne
    doit pas être bloqué par les connexions réussies des autres.
    """
    now = time.time()
    _prune_login_failures(now)
    if len(_login_failures.get(ip, [])) >= settings.max_login_attempts_per_minute:
        raise HTTPException(status_code=429, detail="Trop de tentatives, réessayez plus tard")


def _rate_limit_record_failure(ip: str) -> None:
    now = time.time()
    _login_failures.setdefault(ip, []).append(now)


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
    _rate_limit_check(ip, settings)
    user = db.scalar(select(User).where(User.email == str(body.email).lower()))
    if user is None or not verify_password(body.password, user.password_hash):
        _rate_limit_record_failure(ip)
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


@router.patch("/me")
def patch_me(
    body: ProfilePatch,
    request: Request,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> UserOut:
    """Modification de son propre profil : nom complet, email, mot de passe.

    Le changement de mot de passe exige le mot de passe actuel ; un changement
    d'email re-vérifie l'unicité et invalide la session (reconnexion).
    """
    data = body.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(status_code=422, detail="Aucune modification fournie")
    changed_fields: list[str] = []
    if "password" in data:
        if "current_password" not in data or not verify_password(
            data["current_password"], user.password_hash
        ):
            raise HTTPException(
                status_code=403, detail="Mot de passe actuel incorrect"
            )
        user.password_hash = hash_password(data.pop("password"))
        data.pop("current_password", None)
        changed_fields.append("password")
    if "email" in data:
        new_email = str(data.pop("email")).lower().strip()
        if new_email != user.email:
            if db.scalar(select(User).where(User.email == new_email)):
                raise HTTPException(status_code=409, detail="Email déjà utilisé")
            user.email = new_email
            changed_fields.append("email")
    if "full_name" in data:
        user.full_name = str(data.pop("full_name")).strip()
        changed_fields.append("full_name")
    if data:
        raise HTTPException(status_code=422, detail="Champ(s) inconnu(s)")
    db.commit()
    db.refresh(user)
    audit(
        db,
        "profile.update",
        "user",
        user.id,
        detail=",".join(changed_fields) or "profil",
        user=user,
        ip=request.client.host if request.client else None,
    )
    db.commit()
    return UserOut.model_validate(user)