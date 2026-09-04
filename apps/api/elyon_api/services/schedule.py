from __future__ import annotations

import datetime as dt

from sqlalchemy import select
from sqlalchemy.orm import Session

from elyon_api.models import Schedule, ScheduleExclusion, ensure_utc


def overlaps(
    a_start: dt.datetime, a_end: dt.datetime, b_start: dt.datetime, b_end: dt.datetime
) -> bool:
    a_start, a_end = ensure_utc(a_start), ensure_utc(a_end)
    b_start, b_end = ensure_utc(b_start), ensure_utc(b_end)
    return a_start < b_end and b_start < a_end


def sort_schedules(schedules: list[Schedule]) -> list[Schedule]:
    return sorted(
        schedules,
        key=lambda s: (-s.priority, s.id),
    )


def find_overlaps(
    db: Session, site_id: str, start_at: dt.datetime, end_at: dt.datetime,
    exclude_id: str | None = None,
) -> list[Schedule]:
    stmt = select(Schedule).where(
        Schedule.site_id == site_id,
        Schedule.is_active.is_(True),
    )
    if exclude_id is not None:
        stmt = stmt.where(Schedule.id != exclude_id)
    results = []
    for candidate in db.scalars(stmt):
        if overlaps(start_at, end_at, candidate.start_at, candidate.end_at):
            results.append(candidate)
    return results


def active_schedules(
    db: Session,
    site_id: str,
    at: dt.datetime,
    device_id: str | None = None,
) -> list[Schedule]:
    """Plannings actifs pour un site à l'instant donné.

    Un planning ciblant un device précis (`device_id` renseigné) ne s'applique
    qu'à cet écran ; les plannings sans cible valent pour tous les écrans.
    """
    at = ensure_utc(at)
    stmt = select(Schedule).where(
        Schedule.site_id == site_id,
        Schedule.is_active.is_(True),
        Schedule.start_at <= at,
        Schedule.end_at > at,
    )
    schedules = list(db.scalars(stmt))
    if device_id is not None:
        excluded = set(
            db.scalars(
                select(ScheduleExclusion.schedule_id).where(
                    ScheduleExclusion.device_id == device_id
                )
            )
        )
        schedules = [
            s for s in schedules
            if (s.device_id is None or s.device_id == device_id) and s.id not in excluded
        ]
    return sort_schedules(schedules)