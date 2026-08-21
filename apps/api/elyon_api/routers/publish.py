from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from elyon_api.db import get_db
from elyon_api.deps import audit, get_device_from_request, require_permission, require_site_access
from elyon_api.models import Device, User
from elyon_api.permissions import Permission
from elyon_api.schemas import ManifestOut
from elyon_api.services.manifest import latest_manifest, publish_manifest

router = APIRouter(prefix="/api", tags=["publish"])


def _get_device(db: Session, user: User, device_id: str) -> Device:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="Device introuvable")
    require_site_access(db, user, device.org_id)
    return device


@router.post("/devices/{device_id}/publish")
def publish(
    device_id: str,
    request: Request,
    user: User = Depends(require_permission(Permission.SCHEDULE_PUBLISH)),
    db: Session = Depends(get_db),
) -> ManifestOut:
    device = _get_device(db, user, device_id)
    manifest = publish_manifest(db, device, request.app.state.settings)
    audit(db, "manifest.publish", "device", device.id, detail=f"v{manifest.version}", user=user)
    db.commit()
    return ManifestOut.model_validate(manifest)


@router.get("/devices/{device_id}/manifest")
def fetch_manifest(
    device_id: str,
    device: Device = Depends(get_device_from_request),
    db: Session = Depends(get_db),
) -> ManifestOut:
    if device.id != device_id:
        raise HTTPException(status_code=403, detail="Accès refusé")
    manifest = latest_manifest(db, device_id)
    if manifest is None:
        raise HTTPException(status_code=404, detail="Aucun manifeste publié")
    return ManifestOut.model_validate(manifest)