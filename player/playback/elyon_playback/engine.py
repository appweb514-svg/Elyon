from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from elyon_playback.renderers import Renderer, touch_heartbeat
from elyon_playback.widgets import compose_widget_bar, has_live_widgets, read_widget_feed


def read_show_request(data_dir: Path) -> dict[str, Any] | None:
    """File d'attente « Afficher » posée par l'agent (commande SHOW)."""
    show_file = data_dir / "show" / "request.json"
    if not show_file.exists():
        return None
    try:
        loaded = json.loads(show_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return loaded if isinstance(loaded, dict) else None


def clear_show_request(data_dir: Path) -> None:
    (data_dir / "show" / "request.json").unlink(missing_ok=True)


def write_now_playing(path: Path, payload: dict[str, Any]) -> None:
    """Écrit l'état de lecture de façon atomique (lu par l'agent / le lab)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    tmp.replace(path)


@dataclass(frozen=True)
class PlayItem:
    """Élément élémentaire de la file de lecture (image, page ou vidéo)."""

    kind: str  # "image" | "page" | "video"
    path: Path
    duration_seconds: float | None = None  # None = jusqu'à la fin (vidéo)
    media_id: str = ""
    name: str = ""


def build_queue(layout: dict[str, Any], blob_dir: Path) -> list[PlayItem]:
    """Construit la file de lecture depuis le layout synchronisé.

    Règle de conflit (identique au serveur, lot 5) : priorité desc puis
    schedule_id asc — déterministe. Seul le bloc gagnant est joué.
    """
    blocks = sorted(
        layout.get("blocks", []),
        key=lambda b: (-int(b.get("priority", 0)), str(b.get("schedule_id", ""))),
    )
    media_by_id = {m["media_id"]: m for m in layout.get("media", [])}

    items: list[PlayItem] = []
    if not blocks:
        return items

    winning = blocks[0]
    for entry in winning.get("entries", []):
        media = media_by_id.get(entry.get("media_id"))
        if media is None:
            continue
        duration = float(entry.get("duration_seconds") or 10.0)
        main = blob_dir / media["main_blob"]
        if media["kind"] == "video":
            items.append(
                PlayItem(
                    kind="video",
                    path=main,
                    duration_seconds=None,
                    media_id=media["media_id"],
                    name=media["name"],
                )
            )
        elif media["kind"] in ("pdf", "office"):
            for index, sha in enumerate(media.get("page_blobs", [])):
                items.append(
                    PlayItem(
                        kind="page",
                        path=blob_dir / sha,
                        duration_seconds=duration,
                        media_id=media["media_id"],
                        name=f"{media['name']} p.{index + 1}",
                    )
                )
        else:
            items.append(
                PlayItem(
                    kind="image",
                    path=main,
                    duration_seconds=duration,
                    media_id=media["media_id"],
                    name=media["name"],
                )
            )
    return items


class BlankStateLike(Protocol):
    @property
    def blanked(self) -> bool: ...


class PlaybackEngine:
    """Boucle de lecture : consomme le layout actif du MediaStore.

    Entre chaque élément : heartbeat (fichier), vérification blank, et
    relecture du layout (les changements publiés prennent effet au prochain
    élément — un élément en cours n'est jamais interrompu brutalement).
    """

    def __init__(
        self,
        renderer: Renderer,
        layout_provider: Callable[[], dict[str, Any] | None],
        heartbeat_file: Path,
        blob_dir: Path,
        blank_state: BlankStateLike | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        stop_check: Callable[[], bool] | None = None,
        idle_wait_seconds: float = 1.0,
        show_loop_seconds: float = 10.0,
        status_file: Path | None = None,
        ticker_tick_seconds: float = 0.5,
        play_idle_frames: bool = False,
    ) -> None:
        self.renderer = renderer
        self.layout_provider = layout_provider
        self.heartbeat_file = heartbeat_file
        self.blob_dir = blob_dir
        self.blank_state = blank_state
        self.sleep_fn = sleep_fn
        self.stop_check = stop_check or (lambda: False)
        self.idle_wait_seconds = idle_wait_seconds
        self.status_file = status_file
        self.current_media_id: str | None = None
        self.active_widgets: list[dict[str, Any]] = []
        self.show_reader = read_show_request
        self.show_clear = clear_show_request
        self.show_loop_seconds = show_loop_seconds
        self.ticker_tick_seconds = ticker_tick_seconds
        self.play_idle_frames = play_idle_frames
        self._idle_frame_tick = 0.0

    def _should_stop(self) -> bool:
        return self.stop_check()

    def _publish_status(self, payload: dict[str, Any]) -> None:
        if self.status_file is not None:
            write_now_playing(self.status_file, payload)

    def _write_screen_frame(self, item: PlayItem, display_path: Path | None = None) -> None:
        """Capture de ce qui est à l'écran, lue par le flux « direct » du serveur.

        Images/PDF : copie du fichier affiché (déjà un bitmap, widgets
        composités le cas échéant). Vidéos : une frame est extraite à
        intervalle régulier côté serveur ; le player indique ici le fichier
        source, la capture est rafraîchie par le heartbeat de lecture.
        """
        frame_file = self._data_dir() / "screen-frame.jpg"
        shown = display_path or item.path
        try:
            if item.kind == "video":
                # started_at : le flux « direct » du serveur en déduit la
                # position de lecture pour extraire une frame vivante.
                info = {
                    "video": True,
                    "path": str(shown),
                    "started_at": time.time(),
                }
                (self._data_dir() / "screen-frame.json").write_text(
                    json.dumps(info), encoding="utf-8"
                )
                return
            # Image ou page PDF : le blob affiché EST l'image à l'écran.
            tmp = frame_file.with_suffix(".jpg.tmp")
            tmp.write_bytes(shown.read_bytes())
            tmp.replace(frame_file)
            (self._data_dir() / "screen-frame.json").write_text(
                json.dumps({"video": False}), encoding="utf-8"
            )
        except OSError:
            pass

    def _display_path(self, item: PlayItem) -> Path:
        """Fichier effectivement affiché : image + widgets composés si besoin."""
        widgets = self.active_widgets
        if not widgets or item.kind not in ("image", "page"):
            return item.path
        feed = read_widget_feed(self._data_dir())
        out = self._data_dir() / "render" / f"{item.media_id or 'frame'}.jpg"
        composed = compose_widget_bar(item.path, widgets, feed, out)
        return composed or item.path

    def play_item(self, item: PlayItem) -> None:
        self.current_media_id = item.media_id or None
        # Widget « vivant » (horloge, météo, ticker RSS) : l'image est
        # recomposée à intervalles réguliers pour un affichage en temps réel.
        if item.kind in ("image", "page") and has_live_widgets(self.active_widgets):
            self._play_item_with_ticker(item)
            return
        display_path = self._display_path(item)
        self._publish_status(
            {
                "media_id": item.media_id or None,
                "name": item.name,
                "kind": item.kind,
                "path": str(display_path),
                "state": "playing",
            }
        )
        self._write_screen_frame(item, display_path)
        if item.kind == "video":
            self.renderer.play_video(item.path)
        else:
            duration = item.duration_seconds or 10.0
            self.renderer.play_image(display_path, duration)

    def _play_item_with_ticker(self, item: PlayItem) -> None:
        duration = item.duration_seconds or 10.0
        remaining = duration
        while remaining > 0 and not self._should_stop():
            display_path = self._display_path(item)
            self._publish_status(
                {
                    "media_id": item.media_id or None,
                    "name": item.name,
                    "kind": item.kind,
                    "path": str(display_path),
                    "state": "playing",
                }
            )
            self._write_screen_frame(item, display_path)
            step = min(self.ticker_tick_seconds, remaining)
            self.renderer.play_image(display_path, step)
            remaining -= step

    def _data_dir(self) -> Path:
        return self.blob_dir.parent

    def _sync_widgets(self, layout: dict[str, Any] | None) -> None:
        widgets = (layout or {}).get("widgets")
        self.active_widgets = widgets if isinstance(widgets, list) else []

    def _pending_show_item(self) -> PlayItem | None:
        """L'élément « Afficher » prêt à être joué (fichier déjà téléchargé).

        Retourne None si la spec est absente ou si l'agent télécharge encore
        le média (nouvelle tentative au cycle suivant).
        """
        show = self.show_reader(self._data_dir())
        if show is None or not show.get("media_id"):
            return None
        media_id = str(show["media_id"])
        kind = str(show.get("kind") or "image")
        path = self._data_dir() / "show" / media_id
        if not path.exists():
            return None
        duration = show.get("duration_seconds")
        try:
            duration_f = float(duration) if duration else None
        except (TypeError, ValueError):
            duration_f = None
        return PlayItem(
            kind="video" if kind == "video" else "image",
            path=path,
            duration_seconds=duration_f,
            media_id=media_id,
            name=str(show.get("name") or media_id),
        )

    def _play_show_item(self, request: dict[str, Any]) -> None:
        """Joue l'élément « Afficher » en affichage continu (pas de playliste).

        Durée fixe (duration_seconds) : joué une fois puis consommé.
        Sans durée : rejoué à chaque tour de boucle tant que la spec est en
        place — le média reste visible jusqu'au « Arrêter » (garde à
        l'écran). Quand une playliste est en cours, le média passe plutôt par
        `run_forever` : il est inséré en tête de la file de lecture.
        """
        media_id = str(request.get("media_id") or "")
        kind = str(request.get("kind") or "image")
        duration = request.get("duration_seconds")
        if not media_id:
            self.show_clear(self._data_dir())
            return
        try:
            duration_f = float(duration) if duration else None
        except (TypeError, ValueError):
            duration_f = None
        path = self._data_dir() / "show" / media_id
        if not path.exists():
            # Téléchargement en cours par l'agent — nouvelle tentative au
            # prochain cycle (la spec reste en place).
            self.sleep_fn(0.5)
            return
        self.current_media_id = media_id
        self._publish_status(
            {
                "media_id": media_id,
                "name": request.get("name") or media_id,
                "kind": kind,
                "path": str(path),
                "state": "playing",
                "show": True,
            }
        )
        # Le flux « direct » du mur lit screen-frame.jpg : sans cette capture,
        # l'écran affiché resterait celui du dernier élément de la playliste.
        show_item = PlayItem(
            kind="video" if kind == "video" else "image",
            path=path,
            media_id=media_id,
            name=str(request.get("name") or media_id),
        )
        display_path = self._display_path(show_item)
        self._write_screen_frame(show_item, display_path)
        if duration_f is not None:
            # One-shot : durée fixe puis retour au planning.
            if kind == "video":
                self.renderer.play_video(path)
            else:
                self.renderer.play_image(display_path, duration_f)
            self.show_clear(self._data_dir())
            self.current_media_id = None
            self._publish_status({"media_id": None, "state": "idle"})
            return
        if kind == "video":
            self.renderer.play_video(path)
        else:
            self.renderer.play_image(display_path, self.show_loop_seconds)

    def _play_idle_frame(self, layout: dict[str, Any] | None) -> None:
        """Écran d'attente : fond animé « Affichage en préparation » + widgets.

        Les widgets (texte déroulant notamment) restent visibles même sans
        diffusion. Trame re-rendue toutes les ~2 s pour animer le défilement.
        Seulement pour les rendus réels (mpv) : le rendu factice du lab reste
        en état « idle » et le mur affiche l'animation web.
        """
        if not self.play_idle_frames:
            return
        try:
            from PIL import Image
        except ImportError:
            return
        data_dir = self._data_dir()
        idle_dir = data_dir / "idle"
        idle_dir.mkdir(parents=True, exist_ok=True)
        background = idle_dir / "background.png"
        frame = idle_dir / "frame.jpg"
        if not background.exists():
            try:
                width, height = 1920, 1080
                gradient = Image.new("RGB", (width, height))
                top, bottom = (15, 23, 42), (30, 27, 75)
                px = gradient.load()
                for y in range(height):
                    t = y / max(height - 1, 1)
                    r = int(top[0] + (bottom[0] - top[0]) * t)
                    g = int(top[1] + (bottom[1] - top[1]) * t)
                    b = int(top[2] + (bottom[2] - top[2]) * t)
                    for x in range(width):
                        px[x, y] = (r, g, b)
                gradient.save(background, "PNG")
            except OSError:
                return
        widgets = (layout or {}).get("widgets") or []
        composed = compose_widget_bar(background, widgets, None, frame)
        try:
            self.renderer.play_image(composed or background, 2.0)
        except Exception:  # noqa: BLE001 — l'écran d'attente ne doit jamais tuer la boucle
            pass

    def run_forever(self) -> None:
        was_blanked = False
        # File restante de la playliste en cours : conservée entre les tours
        # de boucle pour que la lecture reprenne là où elle en était (et que
        # les médias « Afficher » s'insèrent dedans).
        queue: list[PlayItem] = []
        while not self._should_stop():
            touch_heartbeat(self.heartbeat_file)
            blanked = self.blank_state.blanked if self.blank_state is not None else False
            if blanked and not was_blanked:
                self.renderer.blank()
                queue = []  # reconstruite au retour du blank
            elif not blanked and was_blanked:
                self.renderer.unblank()
            was_blanked = blanked

            if blanked:
                self.current_media_id = None
                self._publish_status({"media_id": None, "state": "blank"})
                self.sleep_fn(self.idle_wait_seconds)
                continue

            # « Afficher » en attente : le média rejoint la playliste en cours
            # — inséré en tête de file, il passe avant la suite, qui reprend
            # ensuite là où elle en était.
            show = self.show_reader(self._data_dir())
            if show is not None and show.get("media_id"):
                item = self._pending_show_item()
                if item is None:
                    # Téléchargement en cours par l'agent — nouvelle tentative
                    # au prochain cycle (la spec reste en place).
                    self.sleep_fn(0.5)
                    continue
                if not queue:
                    layout = self.layout_provider()
                    self._sync_widgets(layout)
                    queue = build_queue(layout, self.blob_dir) if layout is not None else []
                if queue:
                    self.show_clear(self._data_dir())
                    queue.insert(0, item)
                else:
                    # Pas de playliste : affichage continu jusqu'à « Arrêter ».
                    self._play_show_item(show)
                    continue

            if not queue:
                layout = self.layout_provider()
                self._sync_widgets(layout)
                if layout is None:
                    self.current_media_id = None
                    self._publish_status({"media_id": None, "state": "idle"})
                    self._play_idle_frame(None)
                    self.sleep_fn(self.idle_wait_seconds)
                    continue
                queue = build_queue(layout, self.blob_dir)
                if not queue:
                    self._publish_status({"media_id": None, "state": "idle"})
                    self._play_idle_frame(layout)
                    self.sleep_fn(self.idle_wait_seconds)
                    continue

            self.play_item(queue.pop(0))


def _select_renderer(data_dir: Path) -> Renderer:
    import os

    from elyon_playback.renderers import DummyRenderer, MpvRenderer

    kind = os.environ.get("ELYON_PLAYBACK_RENDERER", "mpv").strip().lower()
    if kind in {"dummy", "headless", "lab"}:
        try:
            speed = float(os.environ.get("ELYON_PLAYBACK_SPEED", "1"))
        except ValueError:
            speed = 1.0
        return DummyRenderer(speed=speed)
    return MpvRenderer()


def main() -> None:
    """Point d'entrée : moteur branché sur le MediaStore local (lot 8)."""
    import sys

    from elyon_playback.renderers import FileBlankState

    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/var/lib/elyon-player")

    def layout_provider() -> dict[str, Any] | None:
        current = data_dir / "current" / "layout.json"
        if not current.exists():
            return None
        try:
            loaded: object = json.loads(current.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                return loaded
            return None
        except (OSError, json.JSONDecodeError):
            return None

    engine = PlaybackEngine(
        renderer=_select_renderer(data_dir),
        layout_provider=layout_provider,
        heartbeat_file=data_dir / "playback.heartbeat",
        blob_dir=data_dir / "blobs",
        blank_state=FileBlankState(data_dir / "blank"),
        status_file=data_dir / "now-playing.json",
        play_idle_frames=(
            os.environ.get("ELYON_PLAYBACK_RENDERER", "mpv").strip().lower()
            not in {"dummy", "headless", "lab"}
        ),
    )
    engine.run_forever()


if __name__ == "__main__":
    main()
