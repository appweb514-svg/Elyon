from __future__ import annotations

import hashlib
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from elyon_api.db import get_db
from elyon_api.deps import (
    audit,
    get_device_from_request,
    require_roles,
    require_same_org,
)
from elyon_api.models import Device, Media, MediaKind, MediaStatus, Role, User
from elyon_api.schemas import MediaOut
from elyon_api.services.storage import build_storage, safe_storage_path

router = APIRouter(prefix="/api/media", tags=["media"])

admin = require_roles(Role.SUPERADMIN, Role.ORG_ADMIN, Role.SITE_MANAGER, Role.OPERATOR)

_EXT_KIND = {
    ".mp4": MediaKind.VIDEO,
    ".webm": MediaKind.VIDEO,
    ".mkv": MediaKind.VIDEO,
    ".mov": MediaKind.VIDEO,
    ".jpg": MediaKind.IMAGE,
    ".jpeg": MediaKind.IMAGE,
    ".png": MediaKind.IMAGE,
    ".gif": MediaKind.IMAGE,
    ".webp": MediaKind.IMAGE,
    ".pdf": MediaKind.PDF,
}


def _kind_for(filename: str, content_type: str) -> MediaKind:
    ext = re.search(r"(\.[a-z0-9]+)$", filename.lower())
    if ext and ext.group(1) in _EXT_KIND:
        return _EXT_KIND[ext.group(1)]
    if content_type.startswith("video/"):
        return MediaKind.VIDEO
    if content_type.startswith("image/"):
        return MediaKind.IMAGE
    if content_type == "application/pdf":
        return MediaKind.PDF
    raise HTTPException(status_code=400, detail="Type de média non supporté")


@router.post("", status_code=201)
def upload_media(
    request: Request,
    file: UploadFile,
    name: str | None = None,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
) -> MediaOut:
    settings = request.app.state.settings
    if user.role != Role.SUPERADMIN:
        org = user.org_id
    else:
        org = None
    if org is None:
        raise HTTPException(status_code=400, detail="org_id requis pour un superadmin")

    kind = _kind_for(file.filename or "", file.content_type or "")
    storage = build_storage(settings)
    sha = hashlib.sha256()
    total = 0
    import uuid as _uuid

    tmp_path = safe_storage_path(f"originals/{user.org_id}/.upload-{_uuid.uuid4().hex}")
    storage.delete(tmp_path)
    while True:
        chunk = file.file.read(1024 * 512)
        if not chunk:
            break
        total += len(chunk)
        if total > settings.max_media_bytes:
            storage.delete(tmp_path)
            raise HTTPException(status_code=413, detail="Fichier trop volumineux")
        sha.update(chunk)
        storage.append(tmp_path, chunk)
    if total == 0:
        storage.delete(tmp_path)
        raise HTTPException(status_code=400, detail="Fichier vide")
    rel_path = safe_storage_path(f"originals/{user.org_id}/{sha.hexdigest()}")
    if storage.exists(rel_path):
        storage.delete(tmp_path)
    else:
        storage.move(tmp_path, rel_path)
    used = db.scalar(
        select(func.coalesce(func.sum(Media.size_bytes), 0)).where(Media.org_id == org)
    ) or 0
    if used + total > settings.org_quota_bytes:
        storage.delete(rel_path)
        raise HTTPException(status_code=413, detail="Quota de l'organisation dépassé")
    media = Media(
        org_id=org,
        name=name or (file.filename or "média"),
        original_filename=file.filename or "unknown",
        kind=kind,
        mime_type=file.content_type or "application/octet-stream",
        size_bytes=total,
        sha256=sha.hexdigest(),
        storage_path=rel_path,
        status=MediaStatus.UPLOADED,
    )
    db.add(media)
    db.commit()
    db.refresh(media)
    audit(db, "media.upload", "media", media.id, detail=f"{kind.value} {total}", user=user)
    db.commit()
    return MediaOut.model_validate(media)


@router.get("")
def list_media(
    kind: MediaKind | None = None,
    status: MediaStatus | None = None,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
) -> list[MediaOut]:
    stmt = select(Media).order_by(Media.created_at.desc())
    if user.role != Role.SUPERADMIN:
        stmt = stmt.where(Media.org_id == user.org_id)
    if kind:
        stmt = stmt.where(Media.kind == kind)
    if status:
        stmt = stmt.where(Media.status == status)
    return [MediaOut.model_validate(m) for m in db.scalars(stmt)]


def _get_media(db: Session, user: User, media_id: str) -> Media:
    media = db.get(Media, media_id)
    if media is None:
        raise HTTPException(status_code=404, detail="Média introuvable")
    require_same_org(db, user, media.org_id)
    return media


@router.get("/{media_id}")
def get_media(
    media_id: str, user: User = Depends(admin), db: Session = Depends(get_db)
) -> MediaOut:
    return MediaOut.model_validate(_get_media(db, user, media_id))


@router.get("/{media_id}/file")
def media_file(
    media_id: str,
    request: Request,
    db: Session = Depends(get_db),
    device: Device = Depends(get_device_from_request),
):
    media = db.get(Media, media_id)
    if media is None or media.org_id != device.org_id:
        raise HTTPException(status_code=404, detail="Média introuvable")
    storage = build_storage(request.app.state.settings)
    return _serve_file(storage, media.storage_path, media.mime_type, media.size_bytes, request)


@router.get("/{media_id}/pages/{index}/file")
def media_page_file(
    media_id: str,
    index: int,
    request: Request,
    db: Session = Depends(get_db),
    device: Device = Depends(get_device_from_request),
):
    media = db.get(Media, media_id)
    if media is None or media.org_id != device.org_id or not media.pages_json:
        raise HTTPException(status_code=404, detail="Média introuvable")
    pages = json.loads(media.pages_json)
    if index < 0 or index >= len(pages):
        raise HTTPException(status_code=404, detail="Page introuvable")
    storage = build_storage(request.app.state.settings)
    return _serve_file(storage, pages[index], "image/png", 0, request)


def _serve_file(storage, rel_path: str, mime_type: str, size: int, request: Request):
    if not storage.exists(rel_path):
        raise HTTPException(status_code=404, detail="Fichier manquant")
    if size <= 0:
        size = storage.size(rel_path)
    range_header = request.headers.get("range")
    if range_header:
        match = re.match(r"bytes=(\d+)-(\d*)$", range_header.strip())
        if match:
            start = int(match.group(1))
            end = int(match.group(2)) if match.group(2) else size - 1
            if start >= size or end < start:
                return Response(
                    status_code=416, headers={"Content-Range": f"bytes */{size}"}
                )
            with storage.open_read(rel_path) as f:
                f.seek(start)
                data = f.read(end - start + 1)
            return Response(
                content=data,
                status_code=206,
                media_type=mime_type,
                headers={
                    "Content-Range": f"bytes {start}-{end}/{size}",
                    "Accept-Ranges": "bytes",
                    "Content-Length": str(len(data)),
                },
            )
    with storage.open_read(rel_path) as f:
        data = f.read()
    return Response(content=data, media_type=mime_type)


@router.delete("/{media_id}", status_code=204)
def delete_media(
    media_id: str,
    request: Request,
    user: User = Depends(admin),
    db: Session = Depends(get_db),
) -> None:
    media = _get_media(db, user, media_id)
    storage = build_storage(request.app.state.settings)
    storage.delete(media.storage_path)
    if media.pages_json:
        try:
            for rel in json.loads(media.pages_json):
                storage.delete(rel)
        except (ValueError, TypeError):
            pass
    db.delete(media)
    db.commit()
    audit(db, "media.delete", "media", media_id, user=user)
    db.commit()