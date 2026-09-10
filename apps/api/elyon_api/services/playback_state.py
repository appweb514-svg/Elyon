"""Auto-enchaînement de la file : état persisté sur la ligne `devices`.

Contrairement à l'ancien module en mémoire, cet état est partagé par toutes
les répliques API : un arrêt manuel sur une réplique gèle bien l'enchaînement
pour les heartbeats traités par une autre.
"""

from __future__ import annotations

import datetime as dt

from elyon_api.models import Device, ensure_utc

QUEUE_FREEZE_SECONDS = 30


def _now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def mark_queue_stopped(device: Device) -> None:
    """Après un arrêt manuel : remise à zéro du curseur + gel 30 s.

    Sans ce gel, un heartbeat en retard (état « playing » périmé du player)
    relance une diffusion venant d'être arrêtée.
    """
    device.queue_started_media_id = None
    device.queue_started_at = None
    device.queue_stop_until = _now() + dt.timedelta(seconds=QUEUE_FREEZE_SECONDS)


def auto_advance_allowed(device: Device) -> bool:
    if device.queue_stop_until is None:
        return True
    return ensure_utc(device.queue_stop_until) <= _now()
