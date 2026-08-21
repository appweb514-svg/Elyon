from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from elyon_api.config import Settings
from elyon_api.models import Media, MediaKind, MediaStatus
from elyon_api.services.storage import LocalStorage, safe_storage_path


def _thumbnail(image_path: Path, out_path: Path, width: int = 320) -> None:
    from PIL import Image, ImageOps

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as img_file:
        img = ImageOps.exif_transpose(img_file)
        img.thumbnail((width, width * 2))
        img.convert("RGB").save(out_path, "JPEG", quality=80)


def _pdf_to_images(pdf_path: Path, out_dir: Path) -> list[str]:
    if shutil.which("pdftoppm") is None:
        raise RuntimeError("pdftoppm indisponible (poppler-utils requis)")
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["pdftoppm", "-png", "-r", "120", str(pdf_path), str(out_dir / "page")],
        check=True,
        capture_output=True,
    )
    pages = sorted(p.name for p in out_dir.glob("page-*.png"))
    if not pages:
        raise RuntimeError("Aucune page produite pour ce PDF")
    return pages


def process_media(media: Media, settings: Settings, storage: LocalStorage | None = None) -> Media:
    storage = storage or LocalStorage(settings.media_storage_root)
    src = storage._abs(media.storage_path)  # noqa: SLF001
    if not src.exists():
        raise FileNotFoundError(f"Média manquant : {media.storage_path}")

    if media.kind == MediaKind.IMAGE:
        thumb_path = safe_storage_path(f"thumbs/{media.id}.jpg")
        _thumbnail(src, storage._abs(thumb_path))  # noqa: SLF001
        media.pages_json = json.dumps([media.storage_path, thumb_path])
    elif media.kind == MediaKind.PDF:
        out_dir = safe_storage_path(f"pdf/{media.id}")
        pages = _pdf_to_images(src, storage._abs(out_dir))  # noqa: SLF001
        media.pages_json = json.dumps([safe_storage_path(f"{out_dir}/{p}") for p in pages])
    media.status = MediaStatus.READY
    return media