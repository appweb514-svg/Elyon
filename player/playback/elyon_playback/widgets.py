"""Rendu des widgets d'écran (météo, RSS, texte, horloge, HTML) sur l'image.

Le moteur affiche des images/pages via mpv : les widgets sont composés en
amont dans le fichier affiché (et donc dans la capture « direct » du mur).
Les vidéos ne sont pas compositées (limitation mpv).
"""

from __future__ import annotations

import html as _html
import math
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _strip_html(value: str) -> str:
    parts: list[str] = []
    inside = False
    for char in _html.unescape(value):
        if char == "<":
            inside = True
        elif char == ">":
            inside = False
            parts.append(" ")
        elif not inside:
            parts.append(char)
    return " ".join("".join(parts).split()).strip()


def widget_text(widget: dict[str, Any], feed: dict[str, Any] | None, now: datetime) -> str:
    """Texte affiché par un widget (params + données serveur éventuelles)."""
    params = widget.get("params") or {}
    kind = str(widget.get("type") or "")
    if kind == "text":
        return str(params.get("text") or "")
    if kind == "ticker":
        return str(params.get("text") or "")
    if kind == "clock":
        fmt = str(params.get("format") or "HH:MM")
        if str(params.get("tz") or "site") == "utc":

            now = now.astimezone(UTC) if now.tzinfo else datetime.now(UTC)
        return now.strftime("%H:%M:%S" if fmt == "HH:MM:SS" else "%H:%M")
    if kind == "weather":
        city = str(params.get("city") or "").strip() or "Météo"
        entry = (feed or {}).get("weather", {}).get(city) or {}
        temp = entry.get("temperature")
        return f"{city} · {temp:.0f}°C" if isinstance(temp, (int, float)) else city
    if kind == "rss":
        url = str(params.get("url") or "").strip()
        entry = (feed or {}).get("rss", {}).get(url) or {}
        items = [str(item) for item in (entry.get("items") or []) if str(item).strip()]
        if not items:
            return "RSS"
        return "  •  ".join(items[:5])
    if kind == "html":
        return _strip_html(str(params.get("html") or ""))
    return ""


BAR_POSITIONS = {
    "top-left",
    "top-right",
    "top-band",
    "center",
    "bottom-left",
    "bottom-center",
    "bottom-right",
    "bottom-ticker",
}


SIZE_SCALES = {"small": 1.0, "medium": 1.5, "large": 2.2}


def widget_scale(widget: dict[str, Any]) -> float:
    """Facteur de taille du widget (petit/moyen/grand) → échelle du texte."""
    raw = str((widget.get("params") or {}).get("size") or "medium")
    return SIZE_SCALES.get(raw, SIZE_SCALES["medium"])


def _slots(widgets: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Un widget visible par emplacement (le dernier de la liste gagne)."""
    slots: dict[str, dict[str, Any]] = {}
    for widget in widgets:
        if not isinstance(widget, dict) or not widget.get("visible", True):
            continue
        position = str(widget.get("position") or "bottom-left")
        if position not in BAR_POSITIONS:
            position = "bottom-left"
        slots[position] = widget
    return slots


def has_ticker(widgets: list[dict[str, Any]]) -> bool:
    """Ticker RSS actif (barre du bas défilante) dans la disposition ?"""
    return any(
        isinstance(widget, dict)
        and widget.get("visible", True)
        and widget.get("type") in ("rss", "ticker")
        and str(widget.get("position") or "") == "bottom-ticker"
        for widget in widgets
    )


LIVE_WIDGET_TYPES = {"clock", "weather"}


def has_live_widgets(widgets: list[dict[str, Any]]) -> bool:
    """Un widget « vivant » est présent : horloge, météo ou ticker RSS.

    Le moteur recompose alors l'image à intervalles réguliers pour que
    l'heure, la prévision et le défilement soient à jour en temps réel.
    """
    return any(
        isinstance(widget, dict)
        and widget.get("visible", True)
        and (
            str(widget.get("type") or "") in LIVE_WIDGET_TYPES
            or (
                widget.get("type") in ("rss", "ticker")
                and str(widget.get("position") or "") == "bottom-ticker"
            )
        )
        for widget in widgets
    )


def weather_icon_kind(code: object) -> str:
    """Code WMO (Open-Meteo) → icône à dessiner."""
    if not isinstance(code, (int, float)) or isinstance(code, bool):
        return "cloud"
    c = int(code)
    if c == 0:
        return "sun"
    if c in (1, 2):
        return "partly"
    if c == 3:
        return "cloud"
    if c in (45, 48):
        return "fog"
    if 51 <= c <= 67 or c in (80, 81, 82):
        return "rain"
    if 71 <= c <= 77 or c in (85, 86):
        return "snow"
    if c >= 95:
        return "thunder"
    return "cloud"


_FR_DAYS = ["lun", "mar", "mer", "jeu", "ven", "sam", "dim"]


def _day_label(date_str: str, index: int, now: datetime) -> str:
    """Libellé court du jour (« lun », « mar » …) pour la prévision.

    `datetime.weekday()` renvoie 0 pour lundi : la table est indexée
    lundi→dimanche (l'ancienne table dimanche→samedi décalait tous les jours).
    """
    try:
        return _FR_DAYS[datetime.strptime(str(date_str)[:10], "%Y-%m-%d").weekday()]
    except ValueError:
        return _FR_DAYS[(now.weekday() + index) % 7]


def _draw_icon(draw: Any, cx: float, cy: float, r: float, kind: str) -> None:
    """Icône météo vectorielle (PIL) centrée en (cx, cy), rayon r."""
    sun = (255, 200, 40, 255)
    cloud = (235, 240, 245, 255)
    rain = (110, 170, 255, 255)
    bolt = (255, 220, 80, 255)

    def cloud_shape(scale: float = 1.0, dx: float = 0.0, dy: float = 0.0) -> None:
        s = r * scale
        x, y = cx + dx, cy + dy
        draw.ellipse((x - s * 0.9, y - s * 0.35, x - s * 0.1, y + s * 0.45), fill=cloud)
        draw.ellipse((x - s * 0.45, y - s * 0.75, x + s * 0.35, y + s * 0.15), fill=cloud)
        draw.ellipse((x - s * 0.05, y - s * 0.45, x + s * 0.75, y + s * 0.35), fill=cloud)
        draw.rectangle((x - s * 0.8, y, x + s * 0.65, y + s * 0.45), fill=cloud)

    def sun_shape(sx: float, sy: float, sr: float) -> None:
        draw.ellipse((sx - sr, sy - sr, sx + sr, sy + sr), fill=sun)
        for angle in range(0, 360, 45):
            rad = math.radians(angle)
            x1 = sx + math.cos(rad) * sr * 1.25
            y1 = sy + math.sin(rad) * sr * 1.25
            x2 = sx + math.cos(rad) * sr * 1.7
            y2 = sy + math.sin(rad) * sr * 1.7
            draw.line((x1, y1, x2, y2), fill=sun, width=max(1, int(r / 6)))

    if kind == "sun":
        sun_shape(cx, cy, r * 0.55)
    elif kind == "partly":
        sun_shape(cx - r * 0.35, cy - r * 0.35, r * 0.4)
        cloud_shape(0.85, r * 0.15, r * 0.2)
    elif kind == "cloud":
        cloud_shape(1.0, 0, 0)
    elif kind == "fog":
        for i, dy in enumerate((-r * 0.35, 0, r * 0.35)):
            w = r * (0.9 if i != 1 else 1.1)
            draw.line(
                (cx - w, cy + dy, cx + w, cy + dy),
                fill=(200, 205, 215, 255),
                width=max(2, int(r / 4)),
            )
    elif kind == "rain":
        cloud_shape(0.9, 0, -r * 0.25)
        for dx in (-r * 0.45, 0, r * 0.45):
            draw.line(
                (cx + dx, cy + r * 0.25, cx + dx - r * 0.15, cy + r * 0.75),
                fill=rain,
                width=max(2, int(r / 5)),
            )
    elif kind == "snow":
        cloud_shape(0.9, 0, -r * 0.25)
        for dx, dy in ((-r * 0.45, r * 0.4), (0, r * 0.65), (r * 0.45, r * 0.4)):
            d = max(2, int(r / 5))
            draw.ellipse(
                (cx + dx - d, cy + dy - d, cx + dx + d, cy + dy + d),
                fill=(255, 255, 255, 255),
            )
    elif kind == "thunder":
        cloud_shape(0.9, 0, -r * 0.3)
        pts = [
            (cx + r * 0.1, cy + r * 0.05),
            (cx - r * 0.25, cy + r * 0.55),
            (cx - r * 0.02, cy + r * 0.55),
            (cx - r * 0.18, cy + r * 0.95),
            (cx + r * 0.3, cy + r * 0.4),
            (cx + r * 0.05, cy + r * 0.4),
        ]
        draw.polygon(pts, fill=bolt)


def load_display_font(size: int) -> Any:
    """Police d'affichage : DejaVu (accents) si présente, sinon la police PIL."""
    from PIL import ImageFont

    try:
        return ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", size=size
        )
    except (OSError, ImportError):
        try:
            return ImageFont.load_default(size=size)
        except TypeError:
            return ImageFont.load_default()


def compose_widget_bar(
    image_path: Path,
    widgets: list[dict[str, Any]],
    feed: dict[str, Any] | None,
    out_path: Path,
) -> Path | None:
    """Incruste une barre de widgets en bas de l'image. Retourne le chemin écrit.

    Retourne None si rien à dessiner ou si PIL/l'image est indisponible —
    l'appelant affiche alors l'original, sans jamais bloquer la lecture.
    """
    slots = _slots(widgets)
    if not slots:
        return None
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        return None
    try:
        base = Image.open(image_path).convert("RGB")
    except OSError:
        return None
    width, height = base.size
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    base_size = max(12, height // 30)
    pad_x = max(6, width // 150)
    pad_y = max(4, height // 90)
    margin = max(8, width // 100)
    now = datetime.now()
    drawn_any = False
    band_bottom: int | None = None  # bas du bandeau haut (météo)
    for position, widget in slots.items():
        scale = widget_scale(widget)
        font_size = int(base_size * scale)
        font = load_display_font(font_size)
        if widget.get("type") == "weather" and _draw_weather_block(
            draw, widget, feed, now, font, font_size, width, height, position, margin, pad_x, pad_y
        ):
            drawn_any = True
            continue
        text = widget_text(widget, feed, now)
        if not text:
            continue
        if position in ("top-band", "center"):
            try:
                bbox = draw.textbbox((0, 0), text, font=font)
            except ValueError:
                continue
            text_w = int(max(bbox[2] - bbox[0], 1))
            text_h = int(max(bbox[3] - bbox[1], 1))
            pad = max(10, font_size // 2)
            if position == "top-band":
                bar_h = text_h + 2 * pad_y
                draw.rounded_rectangle(
                    (0, margin, width, margin + bar_h),
                    radius=max(4, bar_h // 3),
                    fill=(0, 0, 0, 178),
                )
                draw.text(
                    ((width - text_w) // 2, margin + pad_y - bbox[1]),
                    text,
                    font=font,
                    fill=(255, 255, 255, 255),
                )
                band_bottom = margin + bar_h
            else:  # center
                # Troncature : le texte doit tenir dans la largeur (ellipsis).
                max_w = int(width * 0.8) - 2 * pad
                fitted = text
                try:
                    while fitted and draw.textlength(fitted, font=font) > max_w:
                        fitted = fitted[:-2].rstrip() + "…"
                except Exception:  # noqa: BLE001
                    fitted = text
                try:
                    fb = draw.textbbox((0, 0), fitted, font=font)
                except ValueError:
                    continue
                fw, fh = int(fb[2] - fb[0]), int(fb[3] - fb[1])
                bar_w, bar_h = min(fw + 2 * pad, int(width * 0.8)), fh + 2 * pad_y
                draw.rounded_rectangle(
                    (
                        (width - bar_w) // 2,
                        (height - bar_h) // 2,
                        (width + bar_w) // 2,
                        (height + bar_h) // 2,
                    ),
                    radius=max(4, bar_h // 3),
                    fill=(0, 0, 0, 178),
                )
                draw.text(
                    ((width - fw) // 2 - fb[0], (height - fh) // 2 - fb[1]),
                    fitted, font=font, fill=(255, 255, 255, 255),
                )
            drawn_any = True
            continue
        if position == "bottom-ticker":
            if _draw_ticker(draw, width, height, text, font, now):
                drawn_any = True
            continue
        try:
            bbox = draw.textbbox((0, 0), text, font=font)
        except ValueError:
            continue
        text_w = int(bbox[2] - bbox[0])
        text_h = int(bbox[3] - bbox[1])
        if text_w <= 0 or text_w + 2 * pad_x >= width:
            continue
        bar_h = text_h + 2 * pad_y
        bar_w = text_w + 2 * pad_x
        top = position.startswith("top-")
        if position in ("bottom-center", "top-center"):
            bar_x = (width - bar_w) // 2
        elif position in ("bottom-right", "top-right"):
            bar_x = width - bar_w - margin
        else:
            bar_x = margin
        # Horloge/widget haut : sous le bandeau météo s'il existe.
        if top:
            bar_y = (band_bottom + 4) if band_bottom is not None else margin
        else:
            bar_y = height - bar_h - margin
        draw.rounded_rectangle(
            (bar_x, bar_y, bar_x + bar_w, bar_y + bar_h),
            radius=max(4, bar_h // 3),
            fill=(0, 0, 0, 178),
        )
        draw.text(
            (bar_x + pad_x - bbox[0], bar_y + pad_y - bbox[1]),
            text,
            font=font,
            fill=(255, 255, 255, 255),
        )
        drawn_any = True
    if not drawn_any:
        return None
    composited = Image.alpha_composite(base.convert("RGBA"), overlay).convert("RGB")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    try:
        composited.save(tmp, "JPEG", quality=90)
        tmp.replace(out_path)
    except (OSError, ValueError):
        return None
    return out_path


def _draw_weather_block(
    draw: Any,
    widget: dict[str, Any],
    feed: dict[str, Any] | None,
    now: datetime,
    font: Any,
    font_size: int,
    width: int,
    height: int,
    position: str,
    margin: int,
    pad_x: int,
    pad_y: int,
) -> bool:
    """Bloc météo : température courante + icône, puis prévision des jours à
    venir (icônes soleil/nuage/pluie/neige/orage + max/min par jour)."""
    params = widget.get("params") or {}
    city = str(params.get("city") or "").strip() or "Météo"
    entry = (feed or {}).get("weather", {}).get(city) or {}
    temp = entry.get("temperature")
    line1 = f"{city} · {temp:.0f}°C" if isinstance(temp, (int, float)) else city
    forecast = [f for f in (entry.get("forecast") or []) if isinstance(f, dict)][:5]
    try:
        bbox1 = draw.textbbox((0, 0), line1, font=font)
    except ValueError:
        return False
    t1_w = int(bbox1[2] - bbox1[0])
    t1_h = int(bbox1[3] - bbox1[1])
    r = max(8, int(font_size * 0.7))  # rayon des icônes
    gap = max(4, font_size // 3)
    line1_w = t1_w + gap + 2 * r
    cells: list[tuple[str, int, object]] = []
    for index, day in enumerate(forecast):
        mx, mn = day.get("max"), day.get("min")
        if not isinstance(mx, (int, float)) or not isinstance(mn, (int, float)):
            continue
        label = f"{_day_label(str(day.get('date') or ''), index, now)} {mx:.0f}°/{mn:.0f}°"
        try:
            bbox = draw.textbbox((0, 0), label, font=font)
        except ValueError:
            continue
        cells.append((label, int(bbox[2] - bbox[0]), day.get("code")))
    cell_gap = pad_x
    line2_w = sum(2 * r + gap // 2 + cw for _, cw, _ in cells) + cell_gap * max(0, len(cells) - 1)
    content_w = max(line1_w, line2_w)
    block_w = content_w + 2 * pad_x
    if position != "top-band" and block_w >= width - margin:
        return False
    has_days = bool(cells)
    line2_h = max(2 * r, t1_h) if has_days else 0
    gap_lines = pad_y if has_days else 0
    block_h = 2 * pad_y + t1_h + gap_lines + line2_h
    top = position.startswith("top-")
    if position == "top-band":
        # Bandeau pleine largeur (comme le serveur et le player web) : le
        # contenu est centré au lieu d'une boîte collée à gauche.
        bar_x, block_w = 0, width
    elif position in ("bottom-center", "top-center"):
        bar_x = max(margin, (width - block_w) // 2)
    elif position in ("bottom-right", "top-right"):
        bar_x = max(margin, width - block_w - margin)
    else:
        bar_x = margin
    bar_y = margin if top else height - block_h - margin
    draw.rounded_rectangle(
        (bar_x, bar_y, bar_x + block_w, bar_y + block_h),
        radius=max(4, block_h // 4),
        fill=(0, 0, 0, 178),
    )
    content_x = bar_x + max(pad_x, (block_w - content_w) // 2)
    line1_x = content_x + (content_w - line1_w) // 2
    draw.text(
        (line1_x - bbox1[0], bar_y + pad_y - bbox1[1]),
        line1,
        font=font,
        fill=(255, 255, 255, 255),
    )
    icon_cx = line1_x + t1_w + gap + r
    icon_cy = bar_y + pad_y + t1_h / 2
    _draw_icon(draw, icon_cx, icon_cy, r, weather_icon_kind(entry.get("code")))
    x = content_x + (content_w - line2_w) // 2
    y2_center = bar_y + pad_y + t1_h + gap_lines + line2_h / 2
    for label, cw, code in cells:
        _draw_icon(draw, x + r, y2_center, r, weather_icon_kind(code))
        x += 2 * r + gap // 2
        try:
            bbox = draw.textbbox((0, 0), label, font=font)
        except ValueError:
            continue
        text_y = y2_center - bbox[1] - (bbox[3] - bbox[1]) / 2
        draw.text((x - bbox[0], text_y), label, font=font, fill=(255, 255, 255, 255))
        x += cw + cell_gap
    return True


def ticker_x(text_w: int, width: int, now: datetime) -> float:
    """Position x du début du ticker (défilement continu de gauche à droite).

    Vitesse fluide : l'écran est traversé en ~12 s, sans saut (modulo).
    """
    span = width + text_w
    speed = span / 12.0  # px/s
    offset = (now.timestamp() * speed) % span
    return offset - text_w  # entre depuis la gauche, sort par la droite


def _draw_ticker(
    draw: Any,
    width: int,
    height: int,
    text: str,
    font: Any,
    now: datetime,
) -> bool:
    """Barre du bas pleine largeur : message défilant de gauche à droite.

    Le décalage dépend de l'heure : chaque recomposition de l'image par le
    moteur fait avancer le texte de façon continue.
    """
    try:
        bbox = draw.textbbox((0, 0), text, font=font)
    except ValueError:
        return False
    text_w = int(bbox[2] - bbox[0])
    text_h = int(bbox[3] - bbox[1])
    if text_w <= 0:
        return False
    pad_y = max(4, height // 90)
    bar_h = text_h + 2 * pad_y
    bar_y = height - bar_h
    draw.rectangle((0, bar_y, width, height), fill=(0, 0, 0, 200))
    x = ticker_x(text_w, width, now)
    draw.text((x - bbox[0], bar_y + pad_y - bbox[1]), text, font=font, fill=(255, 255, 255, 255))
    return True


def read_widget_feed(data_dir: Path) -> dict[str, Any] | None:
    """Cache `widgets-feed.json` écrit par l'agent (données météo/RSS)."""
    import json

    path = data_dir / "widgets-feed.json"
    if not path.exists():
        return None
    try:
        loaded: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return loaded if isinstance(loaded, dict) else None