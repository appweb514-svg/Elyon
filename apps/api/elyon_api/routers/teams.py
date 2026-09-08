from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from elyon_api.db import get_db
from elyon_api.deps import audit, require_permission, require_same_org
from elyon_api.models import Media, Organization, Role, Team, User
from elyon_api.permissions import Permission
from elyon_api.schemas import TeamCreate, TeamOut, TeamPatch

router = APIRouter(prefix="/api/teams", tags=["teams"])


def _used_bytes(db: Session, team_id: str) -> int:
    return db.scalar(
        select(func.coalesce(func.sum(Media.size_bytes), 0)).where(
            Media.team_id == team_id
        )
    ) or 0


def _members(db: Session, team_id: str) -> int:
    return db.scalar(
        select(func.count()).select_from(User).where(User.team_id == team_id)
    ) or 0


def _out(db: Session, team: Team) -> TeamOut:
    out = TeamOut.model_validate(team)
    out.used_bytes = _used_bytes(db, team.id)
    out.members = _members(db, team.id)
    return out


@router.get("/mine")
def my_team(
    user: User = Depends(require_permission(Permission.MEDIA_UPLOAD)),
    db: Session = Depends(get_db),
) -> TeamOut | None:
    """Équipe de l'utilisateur courant (pour le partage de médias)."""
    if not user.team_id:
        return None
    team = db.get(Team, user.team_id)
    if team is None:
        return None
    return _out(db, team)


@router.get("")
def list_teams(
    user: User = Depends(require_permission(Permission.USER_VIEW)),
    db: Session = Depends(get_db),
) -> list[TeamOut]:
    stmt = select(Team).order_by(Team.name)
    if user.role != Role.SUPERADMIN:
        stmt = stmt.where(Team.org_id == user.org_id)
    return [_out(db, t) for t in db.scalars(stmt)]


@router.post("", status_code=201)
def create_team(
    body: TeamCreate,
    user: User = Depends(require_permission(Permission.USER_EDIT)),
    db: Session = Depends(get_db),
) -> TeamOut:
    org_id = body.org_id or user.org_id
    if org_id is None:
        raise HTTPException(
            status_code=400,
            detail="Organisation requise : choisissez une organisation pour cette équipe",
        )
    if db.get(Organization, org_id) is None:
        raise HTTPException(status_code=404, detail="Organisation introuvable")
    if user.role != Role.SUPERADMIN and org_id != user.org_id:
        raise HTTPException(status_code=403, detail="Hors périmètre organisation")
    team = Team(org_id=org_id, name=body.name, quota_bytes=body.quota_bytes)
    db.add(team)
    db.commit()
    db.refresh(team)
    audit(db, "team.create", "team", team.id, detail=f"quota={body.quota_bytes}", user=user)
    db.commit()
    return _out(db, team)


@router.patch("/{team_id}")
def patch_team(
    team_id: str,
    body: TeamPatch,
    user: User = Depends(require_permission(Permission.USER_EDIT)),
    db: Session = Depends(get_db),
) -> TeamOut:
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Équipe introuvable")
    require_same_org(db, user, team.org_id)
    if body.name is not None:
        team.name = body.name
    if body.quota_bytes is not None:
        team.quota_bytes = body.quota_bytes
    db.commit()
    db.refresh(team)
    audit(db, "team.update", "team", team.id, user=user)
    db.commit()
    return _out(db, team)


@router.delete("/{team_id}", status_code=204)
def delete_team(
    team_id: str,
    user: User = Depends(require_permission(Permission.USER_EDIT)),
    db: Session = Depends(get_db),
) -> None:
    team = db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Équipe introuvable")
    require_same_org(db, user, team.org_id)
    members = _members(db, team.id)
    if members:
        raise HTTPException(
            status_code=409,
            detail=f"Équipe encore constituée de {members} membre(s) — retirez-les d'abord",
        )
    db.delete(team)
    db.commit()
    audit(db, "team.delete", "team", team_id, user=user)
    db.commit()
