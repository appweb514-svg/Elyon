from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from elyon_api.db import get_db
from elyon_api.deps import audit, require_permission, require_roles
from elyon_api.models import Organization, Role, Site, User
from elyon_api.permissions import Permission
from elyon_api.schemas import OrganizationOut, UserCreate, UserOut, UserPatch
from elyon_api.security import hash_password

router = APIRouter(prefix="/api", tags=["users"])

admin = require_roles(Role.SUPERADMIN, Role.ORG_ADMIN)
superadmin = require_roles(Role.SUPERADMIN)


def _get_org(db: Session, user: User, org_id: str | None) -> Organization | None:
    if org_id is None:
        if user.role == Role.SUPERADMIN:
            return None
        org_id = user.org_id
    if user.role != Role.SUPERADMIN and org_id != user.org_id:
        raise HTTPException(status_code=403, detail="Hors périmètre organisation")
    if org_id is None:
        return None
    org = db.get(Organization, org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organisation introuvable")
    return org


@router.get("/organizations")
def list_organizations(
    user: User = Depends(superadmin), db: Session = Depends(get_db)
) -> list[OrganizationOut]:
    return [OrganizationOut.model_validate(o) for o in db.scalars(select(Organization))]


@router.post("/organizations", status_code=201)
def create_organization(
    name: str,
    slug: str,
    quota_bytes: int = 20 * 1024**3,
    user: User = Depends(superadmin),
    db: Session = Depends(get_db),
) -> OrganizationOut:
    org = Organization(name=name, slug=slug, quota_bytes=quota_bytes)
    db.add(org)
    db.commit()
    db.refresh(org)
    audit(db, "organization.create", "organization", org.id, user=user)
    db.commit()
    return OrganizationOut.model_validate(org)


@router.get("/users")
def list_users(
    user: User = Depends(require_permission(Permission.USER_VIEW)),
    db: Session = Depends(get_db),
) -> list[UserOut]:
    stmt = select(User)
    if user.role != Role.SUPERADMIN:
        stmt = stmt.where(User.org_id == user.org_id)
        if user.site_id is not None:
            stmt = stmt.where(
                (User.site_id == user.site_id)
                | (User.site_id.is_(None))
                | (User.role.in_([Role.ORG_ADMIN, Role.SUPERADMIN]))
            )
    return [UserOut.model_validate(u) for u in db.scalars(stmt.order_by(User.created_at))]


@router.post("/users", status_code=201)
def create_user(
    body: UserCreate,
    user: User = Depends(require_permission(Permission.USER_CREATE)),
    db: Session = Depends(get_db),
) -> UserOut:
    if body.role == Role.SUPERADMIN and user.role != Role.SUPERADMIN:
        raise HTTPException(status_code=403, detail="Seul un superadmin crée des superadmins")
    # Seuls superadmin/org_admin créent des utilisateurs (granulaire)
    if body.site_id is not None:
        site = db.get(Site, body.site_id)
        expected_org = _get_org(db, user, body.org_id)
        expected_org_id = expected_org.id if expected_org else user.org_id
        if site is None or site.org_id != expected_org_id:
            raise HTTPException(status_code=400, detail="site_id invalide")
        if body.role not in (Role.SITE_MANAGER, Role.OPERATOR, Role.VIEWER):
            raise HTTPException(status_code=400, detail="site_id réservé aux rôles site")
    org = _get_org(db, user, body.org_id)
    if org is None and body.role != Role.SUPERADMIN:
        raise HTTPException(status_code=400, detail="org_id requis pour ce rôle")
    if db.scalar(select(User).where(User.email == str(body.email).lower())):
        raise HTTPException(status_code=409, detail="Email déjà utilisé")
    new_user = User(
        org_id=org.id if org else None,
        site_id=body.site_id,
        email=str(body.email).lower(),
        password_hash=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
    )
    db.add(new_user)
    db.commit()
    db.refresh(new_user)
    audit(db, "user.create", "user", new_user.id, detail=body.role.value, user=user)
    db.commit()
    return UserOut.model_validate(new_user)


@router.delete("/users/{user_id}", status_code=204)
def delete_user(
    user_id: str,
    user: User = Depends(require_permission(Permission.USER_DELETE)),
    db: Session = Depends(get_db),
) -> None:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    if target.role == Role.SUPERADMIN and user.role != Role.SUPERADMIN:
        raise HTTPException(status_code=403, detail="Accès refusé")
    if user.role != Role.SUPERADMIN and target.org_id != user.org_id:
        raise HTTPException(status_code=403, detail="Hors périmètre organisation")
    if target.id == user.id:
        raise HTTPException(status_code=400, detail="Impossible de supprimer son propre compte")
    db.delete(target)
    db.commit()
    audit(db, "user.delete", "user", user_id, user=user)
    db.commit()


@router.patch("/users/{user_id}")
def patch_user(
    user_id: str,
    body: UserPatch,
    user: User = Depends(require_permission(Permission.USER_EDIT)),
    db: Session = Depends(get_db),
) -> UserOut:
    target = db.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    if target.role == Role.SUPERADMIN and user.role != Role.SUPERADMIN:
        raise HTTPException(status_code=403, detail="Accès refusé")
    if user.role != Role.SUPERADMIN and target.org_id != user.org_id:
        raise HTTPException(status_code=403, detail="Hors périmètre organisation")
    if user.site_id is not None and target.site_id != user.site_id:
        if target.role not in (Role.ORG_ADMIN, Role.SUPERADMIN):
            raise HTTPException(status_code=403, detail="Hors périmètre site")
    if body.role == Role.SUPERADMIN and user.role != Role.SUPERADMIN:
        raise HTTPException(status_code=403, detail="Accès refusé")
    if body.full_name is not None:
        target.full_name = body.full_name
    if body.role is not None:
        target.role = body.role
    if body.site_id is not None:
        if body.site_id == "":
            target.site_id = None
        else:
            site = db.get(Site, body.site_id)
            if site is None or site.org_id != target.org_id:
                raise HTTPException(status_code=400, detail="site_id invalide")
            target.site_id = site.id
    if body.is_active is not None:
        target.is_active = body.is_active
    db.commit()
    db.refresh(target)
    audit(
        db, "user.update", "user", target.id,
        detail=body.model_dump_json(exclude_none=True), user=user,
    )
    db.commit()
    return UserOut.model_validate(target)