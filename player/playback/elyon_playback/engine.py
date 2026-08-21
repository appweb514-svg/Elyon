from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from elyon_playback.renderers import Renderer, touch_heartbeat


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
        elif media["kind"] == "pdf":
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
    blanked: bool


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
        idle_wait_seconds: float = 5.0,
    ) -> None:
        self.renderer = renderer
        self.layout_provider = layout_provider
        self.heartbeat_file = heartbeat_file
        self.blob_dir = blob_dir
        self.blank_state = blank_state
        self.sleep_fn = sleep_fn
        self.stop_check = stop_check or (lambda: False)
        self.idle_wait_seconds = idle_wait_seconds
        self.current_media_id: str | None = None

    def _should_stop(self) -> bool:
        return self.stop_check()

    def play_item(self, item: PlayItem) -> None:
        self.current_media_id = item.media_id or None
        if item.kind == "video":
            self.renderer.play_video(item.path)
        else:
            duration = item.duration_seconds or 10.0
            self.renderer.play_image(item.path, duration)

    def run_forever(self) -> None:
        was_blanked = False
        while not self._should_stop():
            touch_heartbeat(self.heartbeat_file)
            blanked = self.blank_state.blanked if self.blank_state is not None else False
            if blanked and not was_blanked:
                self.renderer.blank()
            elif not blanked and was_blanked:
                self.renderer.unblank()
            was_blanked = blanked

            if blanked:
                self.current_media_id = None
                self.sleep_fn(self.idle_wait_seconds)
                continue

            layout = self.layout_provider()
            if layout is None:
                self.current_media_id = None
                self.sleep_fn(self.idle_wait_seconds)
                continue

            for item in build_queue(layout, self.blob_dir):
                if self._should_stop():
                    return
                touch_heartbeat(self.heartbeat_file)
                if self.blank_state is not None and self.blank_state.blanked:
                    break
                self.play_item(item)


def main() -> None:
    """Point d'entrée : moteur branché sur le MediaStore local (lot 8)."""
    import sys

    from elyon_playback.renderers import MpvRenderer

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
        renderer=MpvRenderer(),
        layout_provider=layout_provider,
        heartbeat_file=data_dir / "playback.heartbeat",
        blob_dir=data_dir / "blobs",
    )
    engine.run_forever()


if __name__ == "__main__":
    main()
