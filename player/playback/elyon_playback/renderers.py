from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol


class Renderer(Protocol):
    """Abstraction du rendu à l'écran (injectable pour les tests)."""

    def play_image(self, path: Path, duration_seconds: float) -> None: ...

    def play_video(self, path: Path) -> None: ...

    def play_url(self, url: str) -> None: ...

    def blank(self) -> None: ...

    def unblank(self) -> None: ...


class MpvRenderer:
    """Rendu via mpv (vidéo H.264/AAC, images, pages PDF pré-converties).

    `play_image`/`play_video` sont bloquants jusqu'à la fin de l'élément ;
    `blank`/`unblank` sont asynchrones (processus dédié écran noir).
    """

    def __init__(self, binary: str = "mpv", extra_args: list[str] | None = None) -> None:
        self.binary = binary
        self.extra_args = extra_args or [
            "--fs",
            "--no-terminal",
            "--no-osd-bar",
            "--loop=no",
        ]
        self._blank_process: subprocess.Popen[bytes] | None = None
        self._black_png: Path | None = None

    def _run(self, args: list[str]) -> None:
        completed = subprocess.run(  # noqa: S603
            [self.binary, *self.extra_args, *args],
            check=False,
            stdin=subprocess.DEVNULL,
        )
        if completed.returncode not in (0, 4):
            # 4 = fin demandée (idle/quit) ; les autres codes sont des erreurs.
            raise RuntimeError(f"mpv a échoué (code {completed.returncode})")

    def play_image(self, path: Path, duration_seconds: float) -> None:
        self._stop_blank()
        self._run([f"--image-display-duration={max(duration_seconds, 0.1)}", str(path)])

    def play_video(self, path: Path) -> None:
        self._stop_blank()
        self._run([str(path)])

    def play_url(self, url: str) -> None:
        # Les URL web sont jouées par Chromium kiosque, pas par mpv.
        raise NotImplementedError("Utiliser ChromiumRenderer pour les URL")

    def blank(self) -> None:
        """Affiche un écran noir (asynchrone, idempotent)."""
        if self._blank_process is not None and self._blank_process.poll() is None:
            return
        if self._black_png is None:
            self._black_png = _black_png()
        self._blank_process = subprocess.Popen(  # noqa: S603
            [
                self.binary,
                *self.extra_args,
                "--image-display-duration=inf",
                str(self._black_png),
            ],
            stdin=subprocess.DEVNULL,
        )

    def unblank(self) -> None:
        self._stop_blank()

    def _stop_blank(self) -> None:
        if self._blank_process is not None:
            self._blank_process.terminate()
            try:
                self._blank_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._blank_process.kill()
            self._blank_process = None


def _black_png() -> Path:
    import tempfile

    from PIL import Image

    handle = tempfile.NamedTemporaryFile(suffix=".png", delete=False)  # noqa: SIM115
    Image.new("RGB", (16, 16), (0, 0, 0)).save(handle, "PNG")
    handle.close()
    return Path(handle.name)


class ChromiumRenderer:
    """Kiosque Chromium pour les éléments web (en ligne uniquement)."""

    def __init__(self, binary: str = "chromium-browser") -> None:
        self.binary = binary

    def play_url(self, url: str, timeout_seconds: float | None = None) -> None:
        process = subprocess.Popen(  # noqa: S603
            [
                self.binary,
                "--kiosk",
                "--noerrdialogs",
                "--disable-infobars",
                "--disable-session-crashed-bubble",
                f"--app={url}",
            ],
            stdin=subprocess.DEVNULL,
        )
        try:
            if timeout_seconds is None:
                process.wait()
            else:
                process.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired:
            pass
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()


class BlankState:
    """État blank/unblank partagé entre l'agent et le moteur."""

    def __init__(self) -> None:
        self.blanked = False

    def blank(self) -> None:
        self.blanked = True

    def unblank(self) -> None:
        self.blanked = False


class FileBlankState:
    """État blank lu depuis un fichier posé par l'agent (commande distante)."""

    def __init__(self, path: Path) -> None:
        self.path = path

    @property
    def blanked(self) -> bool:
        return self.path.exists()

    def blank(self) -> None:
        self.path.write_text("1", encoding="utf-8")

    def unblank(self) -> None:
        self.path.unlink(missing_ok=True)


class DummyRenderer:
    """Rendu headless pour Raspberry émulés / CI : pas d'écran, pas de mpv.

    Écrit l'élément courant dans `status_file` et attend la durée (accélérable
    via `speed`, ex. 20 → 20× plus rapide).
    """

    def __init__(
        self,
        status_file: Path | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        speed: float = 1.0,
    ) -> None:
        self.status_file = status_file
        self.sleep_fn = sleep_fn
        self.speed = max(speed, 0.001)
        self.events: list[tuple[str, object]] = []
        self._blanked = False

    def _sleep(self, seconds: float) -> None:
        self.sleep_fn(max(seconds, 0.0) / self.speed)

    def _status(self, payload: dict[str, object]) -> None:
        if self.status_file is None:
            return
        self.status_file.parent.mkdir(parents=True, exist_ok=True)
        current: dict[str, object] = {}
        try:
            loaded = json.loads(self.status_file.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                current = loaded
        except (OSError, json.JSONDecodeError):
            current = {}
        # Fusion : le moteur publie media_id/name/show ; le renderer complète
        # avec ce qu'il observe (kind, durée, état). Sans fusion, le media_id
        # du média « Afficher » est perdu avant le heartbeat de l'agent.
        current.update(payload)
        tmp = self.status_file.with_suffix(self.status_file.suffix + ".tmp")
        tmp.write_text(json.dumps(current), encoding="utf-8")
        tmp.replace(self.status_file)

    def play_image(self, path: Path, duration_seconds: float) -> None:
        self.events.append(("image", (path, duration_seconds)))
        self._status(
            {
                "kind": "image",
                "path": str(path),
                "duration_seconds": duration_seconds,
                "state": "playing",
            }
        )
        self._sleep(duration_seconds)

    def play_video(self, path: Path) -> None:
        self.events.append(("video", path))
        self._status({"kind": "video", "path": str(path), "state": "playing"})
        self._sleep(1.0)

    def play_url(self, url: str) -> None:
        self.events.append(("url", url))
        self._status({"kind": "url", "path": url, "state": "playing"})
        self._sleep(1.0)

    def blank(self) -> None:
        self.events.append(("blank", None))
        self._blanked = True
        self._status({"state": "blank", "media_id": None})

    def unblank(self) -> None:
        self.events.append(("unblank", None))
        self._blanked = False


def touch_heartbeat(path: Path) -> None:
    """Met à jour l'horodatage de vie du moteur (utilisé par le watchdog)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(time.time()), encoding="utf-8")


def heartbeat_age(path: Path, now: float | None = None) -> float | None:
    """Âge du dernier battement de cœur, None si jamais démarré."""
    if not path.exists():
        return None
    try:
        last = float(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None
    return (now if now is not None else time.time()) - last


def is_hung(path: Path, threshold_seconds: float, now: float | None = None) -> bool:
    age = heartbeat_age(path, now)
    return age is not None and age > threshold_seconds
