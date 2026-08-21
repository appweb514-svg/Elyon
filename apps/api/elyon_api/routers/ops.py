from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from elyon_api.db import get_db
from elyon_api.deps import (
    audit,
    get_device_from_request,
    require_roles,
    require_site_access,
)
from elyon_api.models import (
    Command,
    CommandStatus,
    Device,
    DeviceStatus,
    Event,
    EventLevel,
    Media,
    Role,
    User,
    ensure_utc,
)
from elyon_api.schemas import (
    CommandAck,
    CommandIn,
    CommandOut,
    EventOut,
    HeartbeatIn,
)

router = APIRouter(prefix="/api", tags=["ops"])

admin = require_roles(
    Role.SUPERADMIN, Role.ORG_ADMIN, Role.SITE_MANAGER, Role.OPERATOR, Role.VIEWER
)


def _add_event(db: Session, org_id: str, site_id: str | None, device_id: str | None,
               type_: str, level: EventLevel, message: str, detail: str | None = None) -> None:
    db.add(Event(org_id=org_id, site_id=site_id, device_id=device_id, type=type_,
                 level=level, message=message, detail=detail))


@router.get("/events")
def list_events(
    site_id: str | None = None,
    device_id: str | None = None,
    level: EventLevel | None = None,
    limit: int = 100,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
) -> list[EventOut]:
    stmt = select(Event).order_by(Event.created_at.desc()).limit(min(limit, 500))
    if user.role != Role.SUPERADMIN:
        stmt = stmt.where(Event.org_id == user.org_id)
    if site_id:
        stmt = stmt.where(Event.site_id == site_id)
    if device_id:
        stmt = stmt.where(Event.device_id == device_id)
    if level:
        stmt = stmt.where(Event.level == level)
    return [EventOut.model_validate(e) for e in db.scalars(stmt)]


@router.post("/devices/{device_id}/heartbeat")
def heartbeat(
    device_id: str,
    body: HeartbeatIn,
    request: Request,
    device: Device = Depends(get_device_from_request),
    db: Session = Depends(get_db),
) -> dict:
    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Accès refusé")
    now = dt.datetime.now(dt.UTC)
    settings = request.app.state.settings
    last = ensure_utc(device.last_seen_at) if device.last_seen_at else None
    was_offline = last is None or (now - last).total_seconds() > settings.offline_grace_seconds
    first_seen = device.last_seen_at is None
    device.last_seen_at = now
    db.commit()
    if first_seen:
        _add_event(db, device.org_id, device.site_id, device.id, "device_online",
                   EventLevel.INFO, f"Player {device.name} connecté")
    elif was_offline:
        _add_event(db, device.org_id, device.site_id, device.id, "device_online",
                   EventLevel.INFO, f"Player {device.name} de retour")
    db.commit()
    return {
        "status": "ok",
        "server_time": now.isoformat(),
        "heartbeat_interval_seconds": settings.heartbeat_interval_seconds,
    }


@router.get("/devices/{device_id}/commands")
def fetch_commands(
    device_id: str,
    device: Device = Depends(get_device_from_request),
    db: Session = Depends(get_db),
) -> list[CommandOut]:
    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Accès refusé")
    now = dt.datetime.now(dt.UTC)
    commands = db.scalars(
        select(Command)
        .where(
            Command.device_id == device_id,
            Command.status.in_([CommandStatus.PENDING, CommandStatus.DELIVERED]),
        )
        .order_by(Command.created_at)
    ).all()
    for cmd in commands:
        cmd.status = CommandStatus.DELIVERED
        cmd.delivered_at = now
    db.commit()
    return [CommandOut.model_validate(c) for c in commands]


@router.post("/devices/{device_id}/commands", status_code=201)
def issue_command(
    device_id: str,
    body: CommandIn,
    request: Request,
    user: User = Depends(require_roles(Role.SUPERADMIN, Role.ORG_ADMIN, Role.SITE_MANAGER)),
    db: Session = Depends(get_db),
) -> CommandOut:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device introuvable")
    require_site_access(db, user, device.org_id)
    cmd = Command(
        device_id=device_id,
        type=body.type,
        payload=body.payload,
        issued_by_id=user.id,
    )
    db.add(cmd)
    db.commit()
    db.refresh(cmd)
    audit(db, "command.issue", "command", cmd.id, detail=body.type.value, user=user)
    db.commit()
    return CommandOut.model_validate(cmd)


@router.post("/devices/{device_id}/commands/{command_id}/ack")
def ack_command(
    device_id: str,
    command_id: str,
    body: CommandAck,
    device: Device = Depends(get_device_from_request),
    db: Session = Depends(get_db),
) -> dict:
    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Accès refusé")
    cmd = db.get(Command, command_id)
    if cmd is None or cmd.device_id != device_id:
        raise HTTPException(status_code=404, detail="Commande introuvable")
    cmd.status = CommandStatus.FAILED if body.error else CommandStatus.ACKED
    cmd.error = body.error
    cmd.acked_at = dt.datetime.now(dt.UTC)
    db.commit()
    if body.error:
        _add_event(db, device.org_id, device.site_id, device.id, "command_failed",
                   EventLevel.WARNING, f"Commande {cmd.type.value} échouée : {body.error}")
    db.commit()
    return {"status": "ok"}


def _device_status(device: Device, now: dt.datetime, grace: int) -> str:
    if device.status != DeviceStatus.APPROVED:
        return device.status.value
    if device.last_seen_at is None:
        return "offline"
    last = ensure_utc(device.last_seen_at)
    if (now - last).total_seconds() > grace:
        return "offline"
    return "online"


@router.get("/dashboard")
def dashboard(
    request: Request,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
) -> dict:
    settings = request.app.state.settings
    now = dt.datetime.now(dt.UTC)
    org_where = [] if user.role == Role.SUPERADMIN else [Device.org_id == user.org_id]
    devices = db.scalars(select(Device).where(*org_where)).all()
    online = sum(
        1 for d in devices if _device_status(d, now, settings.offline_grace_seconds) == "online"
    )
    pending = sum(1 for d in devices if d.status == DeviceStatus.PENDING)
    media_count = db.scalar(select(func.count()).select_from(Media))
    events_stmt = select(Event).order_by(Event.created_at.desc()).limit(8)
    if user.role != Role.SUPERADMIN:
        events_stmt = events_stmt.where(Event.org_id == user.org_id)
    recent_events = [EventOut.model_validate(e) for e in db.scalars(events_stmt)]
    return {
        "devices_total": len(devices),
        "devices_online": online,
        "devices_pending": pending,
        "media_count": media_count or 0,
        "recent_events": recent_events,
        "server_time": now.isoformat(),
    }