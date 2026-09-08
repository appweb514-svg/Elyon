from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from elyon_api.config import Settings
from elyon_api.models import Media, MediaKind, MediaStatus
from elyon_api.services.storage import LocalStorage, safe_storage_path

try:  # iPhone (HEIC/HEIF) : opener optionnel
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pillow_heif = None


def _rasterize_vector(src: Path, out_path: Path) -> bool:
    """SVG → PNG (cairosvg) : PIL ne sait pas ouvrir les SVG."""
    import io as _io

    try:
        import cairosvg

        out_path.parent.mkdir(parents=True, exist_ok=True)
        cairosvg.svg2png(url=str(src), write_to=str(out_path), output_width=1920)
        return out_path.exists()
    except Exception:  # noqa: BLE001
        return False


def _thumbnail(image_path: Path, out_path: Path, width: int = 320) -> None:
    from PIL import Image, ImageOps

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(image_path) as img_file:
        img = ImageOps.exif_transpose(img_file)
        img.thumbnail((width, width * 2))
        img.convert("RGB").save(out_path, "JPEG", quality=80)


def _video_thumbnail(video_path: Path, out_path: Path, seek: float = 3.0) -> bool:
    """Vignette JPEG d'une vidéo via ffmpeg (False si indisponible)."""
    if shutil.which("ffmpeg") is None:
        return False
    out_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                "ffmpeg", "-y", "-v", "error",
                "-ss", f"{seek:.2f}", "-i", str(video_path),
                "-frames:v", "1", "-vf", "scale=640:-2",
                str(out_path),
            ],
            check=True,
            capture_output=True,
            timeout=30,
        )
        return out_path.exists()
    except (subprocess.SubprocessError, OSError):
        return False


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


def _office_to_pdf(src: Path, out_dir: Path) -> Path:
    """Convertit un document Office (pptx/docx/odp…) en PDF via LibreOffice.

    Les présentations deviennent ainsi un diaporama : une image par diapositive.
    """
    if shutil.which("soffice") is None and shutil.which("libreoffice") is None:
        raise RuntimeError("LibreOffice requis pour les documents Office")
    out_dir.mkdir(parents=True, exist_ok=True)
    binary = "soffice" if shutil.which("soffice") else "libreoffice"
    subprocess.run(
        [
            binary, "--headless", "--norestore", "--convert-to", "pdf",
            "--outdir", str(out_dir), str(src),
        ],
        check=True,
        capture_output=True,
        timeout=180,
    )
    pdf = out_dir / (src.stem + ".pdf")
    if not pdf.exists():
        raise RuntimeError("La conversion Office → PDF a échoué")
    return pdf


def process_media(media: Media, settings: Settings, storage: LocalStorage | None = None) -> Media:
    storage = storage or LocalStorage(settings.media_storage_root)
    src = storage._abs(media.storage_path)  # noqa: SLF001
    if not src.exists():
        raise FileNotFoundError(f"Média manquant : {media.storage_path}")

    if media.kind == MediaKind.IMAGE:
        thumb_path = safe_storage_path(f"thumbs/{media.id}.jpg")
        raster = src
        if src.suffix.lower() == ".svg":
            raster_png = storage._abs(safe_storage_path(f"thumbs/{media.id}.png"))  # noqa: SLF001
            if _rasterize_vector(src, raster_png):
                raster = raster_png
                media.pages_json = json.dumps([safe_storage_path(f"thumbs/{media.id}.png"), thumb_path])
        # HEIC/HEIF : pillow-heif doit être enregistré (opener ci-dessus).
        _thumbnail(raster, storage._abs(thumb_path))  # noqa: SLF001
        if not media.pages_json:
            media.pages_json = json.dumps([media.storage_path, thumb_path])
    elif media.kind == MediaKind.VIDEO:
        # Vignette de bibliothèque (frame ~3 s) — l'aperçu serveur du mur
        # reste calculé à la volée avec la position de lecture.
        thumb_path = safe_storage_path(f"thumbs/{media.id}.jpg")
        if _video_thumbnail(src, storage._abs(thumb_path)):  # noqa: SLF001
            media.pages_json = json.dumps([media.storage_path, thumb_path])
    elif media.kind == MediaKind.PDF:
        out_dir = safe_storage_path(f"pdf/{media.id}")
        pages = _pdf_to_images(src, storage._abs(out_dir))  # noqa: SLF001
        media.pages_json = json.dumps([safe_storage_path(f"{out_dir}/{p}") for p in pages])
    elif media.kind == MediaKind.OFFICE:
        # Diaporama : conversion en PDF puis une image par page/diapositive.
        out_dir = safe_storage_path(f"office/{media.id}")
        pdf = _office_to_pdf(src, storage._abs(out_dir))  # noqa: SLF001
        rel_pdf = safe_storage_path(f"{out_dir}/{pdf.name}")
        pages_dir = safe_storage_path(f"office/{media.id}/pages")
        pages = _pdf_to_images(pdf, storage._abs(pages_dir))  # noqa: SLF001
        media.pages_json = json.dumps([safe_storage_path(f"{pages_dir}/{p}") for p in pages])
        # Le PDF converti reste téléchargeable / diffusable tel quel.
        media.storage_path = rel_pdf
    media.status = MediaStatus.READY
    return media