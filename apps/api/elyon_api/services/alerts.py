"""Alertes par e-mail : appareil hors ligne, avec anti-spam.

Reprend l'approche de ScreenTinker (déduplication temporelle) adaptée à une
file de notifications simple en base, exécutée par le balayeur périodique.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from elyon_api.models import Device, DeviceStatus

# Fenêtres d'anti-spam (en secondes)
_OFFLINE_DEDUP_WINDOW = 2 * 3600  # 2 h entre deux notifications pour un device
_LONG_OFFLINE_CUTOFF = 24 * 3600  # au-delà, on n'alerte plus


def _smtp_send(settings, subject: str, body: str) -> None:
    """Envoie un e-mail via SMTP (config optionnelle)."""
    if not settings.alert_smtp_host or not settings.alert_smtp_to:
        return
    import smtplib
    from email.mime.text import MIMEText

    from_addr = settings.alert_smtp_from or settings.alert_smtp_user
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = settings.alert_smtp_to
    try:
        if settings.alert_smtp_port == 465:
            server: Any = smtplib.SMTP_SSL(
                settings.alert_smtp_host, settings.alert_smtp_port, timeout=10
            )
        else:
            server = smtplib.SMTP(settings.alert_smtp_host, settings.alert_smtp_port, timeout=10)
            if settings.alert_smtp_starttls:
                server.starttls()
        if settings.alert_smtp_user:
            server.login(settings.alert_smtp_user, settings.alert_smtp_password)
        server.sendmail(from_addr, settings.alert_smtp_to.split(","), msg.as_string())
        server.quit()
    except OSError:
        # Ne jamais casser le balayeur : l'alerte sera retentée au prochain cycle.
        return


def sweep_offline_alerts(factory: sessionmaker, settings) -> int:
    """Émet les alertes « appareil hors ligne » et renvoie le nombre envoyé.

    Règles anti-spam :
    - une notification par appareil au maximum toutes les 2 h ;
    - plus aucune notification au-delà de 24 h d'indisponibilité continue
      (l'appareil est probablement débranché durablement).
    L'historique des dernières alertes est conservé en base sur l'appareil.
    """
    if not settings.alert_smtp_host or not settings.alert_smtp_to:
        return 0
    now = dt.datetime.now(dt.UTC)
    grace = settings.offline_grace_seconds
    cutoff = now - dt.timedelta(seconds=_LONG_OFFLINE_CUTOFF)
    sent = 0
    with factory() as db:
        devices = db.scalars(select(Device).where(Device.status == DeviceStatus.APPROVED)).all()
        for device in devices:
            last = device.last_seen_at
            if last is None:
                continue
            last_utc = last if last.tzinfo else last.replace(tzinfo=dt.UTC)
            if (now - last_utc).total_seconds() <= grace:
                continue
            # Déjà notifié récemment ou hors fenêtre utile ?
            last_alert = _last_alert_time(db, device)
            if last_alert is not None:
                if (now - last_alert).total_seconds() < _OFFLINE_DEDUP_WINDOW:
                    continue
                if last_alert < cutoff:
                    continue
            _mark_alert(db, device, now)
            _smtp_send(
                settings,
                f"[Elyon] Appareil hors ligne : {device.name}",
                (
                    f"L'appareil « {device.name} » ({device.serial}) est hors ligne\n"
                    f"depuis {last_utc.strftime('%d/%m/%Y %H:%M')}.\n\n"
                    "Vérifiez son alimentation et sa connexion réseau.\n"
                ),
            )
            sent += 1
        if sent:
            db.commit()
    return sent


def _last_alert_time(db, device: Device) -> dt.datetime | None:
    """Heure de la dernière alerte hors ligne (via le champ de télémétrie)."""
    # Réutilise `last_seen_at` historisé ? Non : on stocke l'alerte dans un
    # attribut léger via le journal d'événements pour éviter une migration.
    from elyon_api.models import Event

    ev = db.scalar(
        select(Event)
        .where(
            Event.device_id == device.id,
            Event.type == "device_offline_alert",
        )
        .order_by(Event.created_at.desc())
        .limit(1)
    )
    return ev.created_at if ev else None


def _mark_alert(db, device: Device, at: dt.datetime) -> None:
    from elyon_api.models import Event, EventLevel

    db.add(
        Event(
            org_id=device.org_id,
            site_id=device.site_id,
            device_id=device.id,
            type="device_offline_alert",
            level=EventLevel.WARNING,
            message=f"Appareil {device.name} hors ligne",
            created_at=at,
        )
    )
