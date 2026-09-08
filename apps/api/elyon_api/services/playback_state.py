"""État de lecture transitoire partagé entre les routers (en mémoire)."""
from __future__ import annotations

import time

# device_id → (media_id, monotonic_start, seuil_secondes)
queue_cursor: dict[str, tuple[str, float, float | None]] = {}
# device_id → monotonic : gel de l'auto-enchaînement après un arrêt manuel
queue_stop_guard: dict[str, float] = {}


def mark_queue_stopped(device_id: str) -> None:
    """Après un arrêt manuel : remise à zéro du curseur + gel 30 s.

    Sans ce gel, un heartbeat en retard (état « playing » périmé du player)
    relance une diffusion venant d'être arrêtée.
    """
    queue_cursor.pop(device_id, None)
    queue_stop_guard[device_id] = time.monotonic()


def auto_advance_allowed(device_id: str, freeze_seconds: float = 30.0) -> bool:
    stop = queue_stop_guard.get(device_id)
    return stop is None or time.monotonic() - stop >= freeze_seconds
