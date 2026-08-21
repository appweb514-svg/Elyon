from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from elyon_api.db import get_db
from elyon_api.deps import audit, require_roles, require_same_org, require_site_access
from elyon_api.models import (
    Event,
    EventLevel,
    Media,
    Playlist,
    PlaylistItem,
    Role,
    Schedule,
    Site,
    User,
)
from elyon_api.schemas import (
    PlaylistCreate,
    PlaylistDetailOut,
    PlaylistItemIn,
    PlaylistItemOut,
    PlaylistOut,
    ScheduleCreate,
    ScheduleOut,
    SchedulePatch,
)
from elyon_api.services.schedule import find_overlaps

router = APIRouter(prefix="/api", tags=["content"])

admin = require_roles(Role.SUPERADMIN, Role.ORG_ADMIN, Role.SITE_MANAGER, Role.OPERATOR)
manager = require_roles(Role.SUPERADMIN, Role.ORG_ADMIN, Role.SITE_MANAGER)


@router.get("/playlists")
def list_playlists(user: User = Depends(admin), db: Session = Depends(get_db)) -> list[PlaylistOut]:
    stmt = select(Playlist).order_by(Playlist.name)
    if user.role != Role.SUPERADMIN:
        stmt = stmt.where(Playlist.org_id == user.org_id)
    return [PlaylistOut.model_validate(p) for p in db.scalars(stmt)]


def _get_playlist(db: Session, user: User, playlist_id: str) -> Playlist:
    playlist = db.get(Playlist, playlist_id)
    if playlist is None:
        raise HTTPException(status_code=404, detail="Playlist introuvable")
    require_same_org(db, user, playlist.org_id)
    return playlist


@router.post("/playlists", status_code=201)
def create_playlist(
    body: PlaylistCreate,
    user: User = Depends(manager),
    db: Session = Depends(get_db),
) -> PlaylistOut:
    if user.role == Role.SUPERADMIN:
        raise HTTPException(status_code=400, detail="org_id requis pour un superadmin")
    if db.scalar(
        select(Playlist).where(Playlist.org_id == user.org_id, Playlist.name == body.name)
    ):
        raise HTTPException(status_code=409, detail="Playlist déjà existante")
    playlist = Playlist(org_id=user.org_id, name=body.name, description=body.description)
    db.add(playlist)
    db.commit()
    db.refresh(playlist)
    audit(db, "playlist.create", "playlist", playlist.id, user=user)
    db.commit()
    return PlaylistOut.model_validate(playlist)


@router.get("/playlists/{playlist_id}")
def get_playlist(
    playlist_id: str, user: User = Depends(admin), db: Session = Depends(get_db)
) -> PlaylistDetailOut:
    playlist = _get_playlist(db, user, playlist_id)
    out = PlaylistDetailOut.model_validate(playlist)
    out.items = [PlaylistItemOut.model_validate(i) for i in playlist.items]
    return out


@router.delete("/playlists/{playlist_id}", status_code=204)
def delete_playlist(
    playlist_id: str, user: User = Depends(manager), db: Session = Depends(get_db)
) -> None:
    playlist = _get_playlist(db, user, playlist_id)
    db.delete(playlist)
    db.commit()
    audit(db, "playlist.delete", "playlist", playlist_id, user=user)
    db.commit()


@router.post("/playlists/{playlist_id}/items", status_code=201)
def add_item(
    playlist_id: str,
    body: PlaylistItemIn,
    user: User = Depends(manager),
    db: Session = Depends(get_db),
) -> PlaylistDetailOut:
    playlist = _get_playlist(db, user, playlist_id)
    media = db.get(Media, body.media_id)
    if media is None or media.org_id != playlist.org_id:
        raise HTTPException(status_code=400, detail="Média invalide")
    next_pos = db.scalar(
        select(func.max(PlaylistItem.position)).where(PlaylistItem.playlist_id == playlist.id)
    ) or 0
    item = PlaylistItem(
        playlist_id=playlist.id,
        media_id=media.id,
        position=next_pos + 1,
        duration_seconds=body.duration_seconds,
    )
    db.add(item)
    db.commit()
    db.refresh(playlist)
    audit(db, "playlist.add_item", "playlist", playlist.id, detail=media.id, user=user)
    db.commit()
    out = PlaylistDetailOut.model_validate(playlist)
    out.items = [PlaylistItemOut.model_validate(i) for i in playlist.items]
    return out


@router.delete("/playlists/{playlist_id}/items/{item_id}", status_code=204)
def remove_item(
    playlist_id: str,
    item_id: str,
    user: User = Depends(manager),
    db: Session = Depends(get_db),
) -> None:
    playlist = _get_playlist(db, user, playlist_id)
    item = db.get(PlaylistItem, item_id)
    if item is None or item.playlist_id != playlist.id:
        raise HTTPException(status_code=404, detail="Élément introuvable")
    db.delete(item)
    db.commit()
    audit(db, "playlist.remove_item", "playlist", playlist.id, detail=item_id, user=user)
    db.commit()


@router.post("/playlists/{playlist_id}/reorder")
def reorder_items(
    playlist_id: str,
    item_ids: list[str],
    user: User = Depends(manager),
    db: Session = Depends(get_db),
) -> PlaylistDetailOut:
    playlist = _get_playlist(db, user, playlist_id)
    existing = {item.id: item for item in playlist.items}
    if set(item_ids) != set(existing):
        raise HTTPException(status_code=400, detail="Liste d'éléments incomplète")
    for position, item_id in enumerate(item_ids, start=1):
        existing[item_id].position = position
    db.commit()
    db.refresh(playlist)
    out = PlaylistDetailOut.model_validate(playlist)
    out.items = [PlaylistItemOut.model_validate(i) for i in playlist.items]
    return out


def _get_site(db: Session, user: User, site_id: str) -> Site:
    site = db.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site introuvable")
    require_site_access(db, user, site.org_id)
    return site


@router.get("/schedules")
def list_schedules(
    site_id: str | None = None,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
) -> list[ScheduleOut]:
    stmt = select(Schedule).order_by(Schedule.start_at.desc())
    if user.role != Role.SUPERADMIN:
        stmt = stmt.where(Schedule.org_id == user.org_id)
    if site_id:
        stmt = stmt.where(Schedule.site_id == site_id)
    return [ScheduleOut.model_validate(s) for s in db.scalars(stmt)]


@router.post("/schedules", status_code=201)
def create_schedule(
    body: ScheduleCreate,
    user: User = Depends(manager),
    db: Session = Depends(get_db),
) -> ScheduleOut:
    if body.end_at <= body.start_at:
        raise HTTPException(status_code=422, detail="end_at doit suivre start_at")
    site = _get_site(db, user, body.site_id)
    playlist = db.get(Playlist, body.playlist_id)
    if playlist is None or playlist.org_id != site.org_id:
        raise HTTPException(status_code=400, detail="Playlist invalide")
    overlaps = find_overlaps(db, site.id, body.start_at, body.end_at)
    if overlaps:
        names = ", ".join(o.name for o in overlaps)
        db.add(
            Event(
                org_id=site.org_id,
                site_id=site.id,
                type="schedule_conflict",
                level=EventLevel.WARNING,
                message=f"Conflit de planning avec : {names}",
            )
        )
        db.commit()
    schedule = Schedule(
        org_id=site.org_id,
        site_id=site.id,
        playlist_id=playlist.id,
        name=body.name,
        start_at=body.start_at,
        end_at=body.end_at,
        priority=body.priority,
        is_active=body.is_active,
    )
    db.add(schedule)
    db.commit()
    db.refresh(schedule)
    audit(
        db, "schedule.create", "schedule", schedule.id,
        detail=f"priority={body.priority}", user=user,
    )
    db.commit()
    return ScheduleOut.model_validate(schedule)


def _get_schedule(db: Session, user: User, schedule_id: str) -> Schedule:
    schedule = db.get(Schedule, schedule_id)
    if schedule is None:
        raise HTTPException(status_code=404, detail="Planning introuvable")
    require_site_access(db, user, schedule.org_id)
    return schedule


@router.patch("/schedules/{schedule_id}")
def patch_schedule(
    schedule_id: str,
    body: SchedulePatch,
    user: User = Depends(manager),
    db: Session = Depends(get_db),
) -> ScheduleOut:
    schedule = _get_schedule(db, user, schedule_id)
    data = body.model_dump(exclude_none=True)
    if "playlist_id" in data:
        playlist = db.get(Playlist, data["playlist_id"])
        if playlist is None or playlist.org_id != schedule.org_id:
            raise HTTPException(status_code=400, detail="Playlist invalide")
    start = data.get("start_at", schedule.start_at)
    end = data.get("end_at", schedule.end_at)
    if end <= start:
        raise HTTPException(status_code=422, detail="end_at doit suivre start_at")
    for key, value in data.items():
        setattr(schedule, key, value)
    db.commit()
    db.refresh(schedule)
    audit(db, "schedule.update", "schedule", schedule.id, user=user)
    db.commit()
    return ScheduleOut.model_validate(schedule)


@router.delete("/schedules/{schedule_id}", status_code=204)
def delete_schedule(
    schedule_id: str, user: User = Depends(manager), db: Session = Depends(get_db)
) -> None:
    schedule = _get_schedule(db, user, schedule_id)
    db.delete(schedule)
    db.commit()
    audit(db, "schedule.delete", "schedule", schedule_id, user=user)
    db.commit()