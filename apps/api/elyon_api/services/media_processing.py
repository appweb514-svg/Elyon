from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from elyon_api.config import Settings
from elyon_api.models import Media, MediaKind, MediaStatus
from elyon_api.services.storage import StorageBackend, build_storage, safe_storage_path

try:  # iPhone (HEIC/HEIF) : opener optionnel
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pillow_heif = None  # type: ignore[assignment]


def _rasterize_vector(src: Path, out_path: Path) -> bool:
    """SVG → PNG (cairosvg) : PIL ne sait pas ouvrir les SVG."""
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
    try:
        subprocess.run(
            ["pdftoppm", "-png", "-r", "120", str(pdf_path), str(out_dir / "page")],
            check=True,
            capture_output=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Conversion PDF expirée") from exc
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


def _download_source(storage: StorageBackend, media: Media, dest: Path) -> None:
    """Copie le fichier source du backend de stockage vers un fichier temporaire."""
    with dest.open("wb") as out:
        for chunk in storage.iter_read(media.storage_path):
            out.write(chunk)


def _upload(storage: StorageBackend, rel_path: str, local_path: Path) -> None:
    with local_path.open("rb") as handle:
        storage.write(safe_storage_path(rel_path), handle)


def process_media(
    media: Media, settings: Settings, storage: StorageBackend | None = None
) -> Media:
    """Convertit un média (vignette, PDF/Office → pages) puis publie le résultat.

    Tout le travail se fait dans un dossier temporaire : aucun accès direct au
    disque du backend, donc compatible stockage local **et S3**. Le paramètre
    `storage` permet d'injecter un backend (tests, outillage).
    """
    storage = storage or build_storage(settings)
    with tempfile.TemporaryDirectory(prefix="elyon-media-") as tmp_raw:
        tmp = Path(tmp_raw)
        suffix = Path(media.storage_path).suffix
        source = tmp / f"source{suffix}"
        _download_source(storage, media, source)

        if media.kind == MediaKind.IMAGE:
            thumb_rel = f"thumbs/{media.id}.jpg"
            raster = source
            page_rels: list[str] = []
            if source.suffix.lower() == ".svg":
                raster_rel = f"thumbs/{media.id}.png"
                raster_local = tmp / "raster.png"
                if _rasterize_vector(source, raster_local):
                    _upload(storage, raster_rel, raster_local)
                    raster = raster_local
                    page_rels.append(raster_rel)
            thumb_local = tmp / "thumb.jpg"
            _thumbnail(raster, thumb_local)
            _upload(storage, thumb_rel, thumb_local)
            if page_rels:
                media.pages_json = json.dumps([*page_rels, thumb_rel])
            else:
                media.pages_json = json.dumps([media.storage_path, thumb_rel])
        elif media.kind == MediaKind.VIDEO:
            # Vignette de bibliothèque (frame ~3 s) — l'aperçu serveur du mur
            # reste calculé à la volée avec la position de lecture.
            thumb_rel = f"thumbs/{media.id}.jpg"
            thumb_local = tmp / "thumb.jpg"
            if _video_thumbnail(source, thumb_local):
                _upload(storage, thumb_rel, thumb_local)
                media.pages_json = json.dumps([media.storage_path, thumb_rel])
        elif media.kind == MediaKind.PDF:
            pages_dir = tmp / "pages"
            names = _pdf_to_images(source, pages_dir)
            rels: list[str] = []
            for name in names:
                rel = f"pdf/{media.id}/{name}"
                _upload(storage, rel, pages_dir / name)
                rels.append(rel)
            media.pages_json = json.dumps(rels)
        elif media.kind == MediaKind.OFFICE:
            # Diaporama : conversion en PDF puis une image par page/diapositive.
            office_dir = tmp / "office"
            pdf = _office_to_pdf(source, office_dir)
            pdf_rel = f"office/{media.id}/{pdf.name}"
            _upload(storage, pdf_rel, pdf)
            pages_dir = office_dir / "pages"
            names = _pdf_to_images(pdf, pages_dir)
            rels = []
            for name in names:
                rel = f"office/{media.id}/pages/{name}"
                _upload(storage, rel, pages_dir / name)
                rels.append(rel)
            media.pages_json = json.dumps(rels)
            # Le PDF converti reste téléchargeable / diffusable tel quel.
            media.storage_path = safe_storage_path(pdf_rel)
    media.status = MediaStatus.READY
    return media
