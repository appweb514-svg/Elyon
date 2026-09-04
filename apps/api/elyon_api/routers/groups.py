from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from elyon_api.db import get_db
from elyon_api.deps import audit, require_permission, require_same_org
from elyon_api.models import (
    Command,
    Device,
    DeviceGroup,
    DeviceGroupMember,
    Role,
    User,
)
from elyon_api.permissions import Permission
from elyon_api.schemas import CommandIn

router = APIRouter(prefix="/api", tags=["groups"])


def _out(group: DeviceGroup) -> dict:
    return {
        "id": group.id,
        "org_id": group.org_id,
        "name": group.name,
        "created_at": group.created_at,
        "device_ids": [m.device_id for m in group.members],
    }


@router.get("/device-groups")
def list_groups(
    user: User = Depends(require_permission(Permission.DEVICE_VIEW)),
    db: Session = Depends(get_db),
) -> list[dict]:
    stmt = select(DeviceGroup).order_by(DeviceGroup.name)
    if user.role != Role.SUPERADMIN:
        stmt = stmt.where(DeviceGroup.org_id == user.org_id)
    return [_out(g) for g in db.scalars(stmt)]


@router.post("/device-groups", status_code=201)
def create_group(
    name: str,
    body: list[str],
    user: User = Depends(require_permission(Permission.DEVICE_UPDATE)),
    db: Session = Depends(get_db),
) -> dict:
    if user.org_id is None:
        raise HTTPException(status_code=400, detail="Rattaché à aucune organisation")
    if db.scalar(
        select(DeviceGroup).where(
            DeviceGroup.org_id == user.org_id, DeviceGroup.name == name
        )
    ):
        raise HTTPException(status_code=409, detail="Groupe déjà existant")
    group = DeviceGroup(org_id=user.org_id, name=name)
    db.add(group)
    db.flush()
    for device_id in body:
        device = db.get(Device, device_id)
        if device is None or device.org_id != user.org_id:
            raise HTTPException(status_code=400, detail=f"Appareil invalide : {device_id}")
        db.add(DeviceGroupMember(group_id=group.id, device_id=device.id))
    db.commit()
    db.refresh(group)
    audit(db, "device_group.create", "device_group", group.id, user=user)
    db.commit()
    return _out(group)


@router.patch("/device-groups/{group_id}")
def update_group(
    group_id: str,
    name: str | None = None,
    body: list[str] | None = None,
    user: User = Depends(require_permission(Permission.DEVICE_UPDATE)),
    db: Session = Depends(get_db),
) -> dict:
    group = db.get(DeviceGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Groupe introuvable")
    require_same_org(db, user, group.org_id)
    if name is not None:
        group.name = name
    if body is not None:
        for m in group.members:
            db.delete(m)
        for device_id in body:
            device = db.get(Device, device_id)
            if device is None or device.org_id != group.org_id:
                raise HTTPException(status_code=400, detail=f"Appareil invalide : {device_id}")
            db.add(DeviceGroupMember(group_id=group.id, device_id=device.id))
    db.commit()
    db.refresh(group)
    audit(db, "device_group.update", "device_group", group.id, user=user)
    db.commit()
    return _out(group)


@router.delete("/device-groups/{group_id}", status_code=204)
def delete_group(
    group_id: str,
    user: User = Depends(require_permission(Permission.DEVICE_UPDATE)),
    db: Session = Depends(get_db),
) -> None:
    group = db.get(DeviceGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Groupe introuvable")
    require_same_org(db, user, group.org_id)
    db.delete(group)
    db.commit()
    audit(db, "device_group.delete", "device_group", group_id, user=user)
    db.commit()


@router.post("/device-groups/{group_id}/commands", status_code=201)
def group_command(
    group_id: str,
    body: CommandIn,
    user: User = Depends(require_permission(Permission.DEVICE_COMMAND)),
    db: Session = Depends(get_db),
) -> dict:
    """Envoie une commande à tous les appareils du groupe."""
    group = db.get(DeviceGroup, group_id)
    if group is None:
        raise HTTPException(status_code=404, detail="Groupe introuvable")
    require_same_org(db, user, group.org_id)
    count = 0
    for member in group.members:
        db.add(
            Command(
                device_id=member.device_id,
                type=body.type,
                payload=body.payload,
                issued_by_id=user.id,
            )
        )
        count += 1
    db.commit()
    audit(
        db, "device_group.command", "device_group", group.id,
        detail=f"{body.type.value} → {count} appareil(s)", user=user,
    )
    db.commit()
    return {"command": body.type.value, "devices": count}
