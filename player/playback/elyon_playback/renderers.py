from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import time
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Protocol


class Renderer(Protocol):
    """Abstraction du rendu à l'écran (injectable pour les tests)."""

    def play_image(self, path: Path, duration_seconds: float) -> None: ...

    def play_video(self, path: Path) -> None: ...

    def play_url(self, url: str, timeout_seconds: float | None = None) -> None: ...

    def blank(self) -> None: ...

    def unblank(self) -> None: ...

    def hold_paused_frame(
        self,
        check_paused: Callable[[], bool],
        keepalive: Callable[[], None] | None = None,
    ) -> None:
        """Figé par le « Pause » back-office : bloque le rendu courant.

        `keepalive` (si fourni) est appelé pendant l'attente : le moteur y
        rafraîchit son heartbeat de supervision pendant les pauses longues.
        """


class MpvRenderer:
    """Rendu via mpv (vidéo H.264/AAC, images, pages PDF pré-converties).

    `play_image`/`play_video` sont bloquants jusqu'à la fin de l'élément ;
    `blank`/`unblank` sont asynchrones (processus dédié écran noir).
    Le gel « Pause » s'appuie sur l'IPC mpv (`--input-ipc-server`) : la
    lecture en cours est figée immédiatement à l'image courante puis
    relancée au dégel, sans attendre la fin de l'élément.
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
        self._ipc_socket = uuid.uuid4().hex
        self._ipc_socket_path = Path(f"/tmp/elyon-mpv-{self._ipc_socket}.sock")
        self._ipc_args = [
            f"--input-ipc-server={self._ipc_socket_path}",
            "--idle=no",
        ]

    def _run(self, args: list[str]) -> None:
        socket_path = self._ipc_socket_path
        try:
            socket_path.unlink(missing_ok=True)
        except OSError:
            pass
        completed = subprocess.run(  # noqa: S603
            [self.binary, *self.extra_args, *self._ipc_args, *args],
            check=False,
            stdin=subprocess.DEVNULL,
        )
        if completed.returncode not in (0, 4):
            # 4 = fin demandée (idle/quit) ; les autres codes sont des erreurs.
            raise RuntimeError(f"mpv a échoué (code {completed.returncode})")
        try:
            socket_path.unlink(missing_ok=True)
        except OSError:
            pass

    def play_image(self, path: Path, duration_seconds: float) -> None:
        self._stop_blank()
        self._run([f"--image-display-duration={max(duration_seconds, 0.1)}", str(path)])

    def play_video(self, path: Path) -> None:
        self._stop_blank()
        self._run([str(path)])

    def play_url(self, url: str, timeout_seconds: float | None = None) -> None:
        # Les URL web sont jouées par Chromium kiosque, pas par mpv.
        raise NotImplementedError("Utiliser ChromiumRenderer pour les URL")

    def hold_paused_frame(
        self,
        check_paused: Callable[[], bool],
        keepalive: Callable[[], None] | None = None,
    ) -> None:
        """Figé par le « Pause » back-office : bloque le rendu courant.

        Ordre des mécanismes, du plus réactif au plus universel :
        1. IPC mpv : `set pause yes` fige la lecture à l'image courante ;
           `set pause no` au dégel, la vidéo reprend où elle en était.
        2. Sans IPC (socket indisponible, mpv trop vieux) : SIGSTOP/SIGCONT
           sur LE processus mpv média de ce player (socket IPC en cmdline).
        Tant que `check_paused()` reste vrai, on maintient le gel.
        """
        hint = str(self._ipc_socket_path)
        pids: list[int] = []
        frozen_ipc = False
        # 1) IPC : fige la lecture à l'image courante (le plus précis).
        if mpv_ipc_command("set pause yes", self._ipc_socket_path, 1.0):
            frozen_ipc = True
        else:
            # 2) Repli : SIGSTOP sur le mpv média de ce player.
            pids = mpv_media_pids(hint)
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGSTOP)
                except OSError:
                    continue
            if not pids:
                return  # rien à figer : l'élément s'est déjà terminé
        try:
            while check_paused():
                if keepalive is not None:
                    keepalive()
                time.sleep(0.2)
        finally:
            if frozen_ipc:
                mpv_ipc_command("set pause no", self._ipc_socket_path, 1.0)
            for pid in pids:
                try:
                    os.kill(pid, signal.SIGCONT)
                except OSError:
                    continue

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


def mpv_ipc_command(command: str, socket_path: Path, timeout: float = 2.0) -> bool:
    """Envoie une commande mpv via l'IPC unix (fire-and-forget).

    Retourne True si mpv a répondu ``success``. Les erreurs (socket absent,
    timeout, mpv sans IPC) sont silencieuses : le gel reste piloté par le
    fichier `pause` dans tous les cas.
    """
    if not socket_path.exists():
        return False
    deadline = time.monotonic() + timeout
    message = f'{{ "command": ["{command}"] }}\n'
    while time.monotonic() < deadline:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as conn:
                conn.settimeout(0.5)
                conn.connect(str(socket_path))
                conn.sendall(message.encode("utf-8"))
                reply = conn.makefile("r", encoding="utf-8").readline()
        except OSError:
            time.sleep(0.1)
            continue
        try:
            return bool(json.loads(reply).get("error") == "success")
        except (json.JSONDecodeError, ValueError):
            return False
    return False


def mpv_media_pids(socket_hint: str | None = None) -> list[int]:
    """PIDs mpv en train de lire un média (hors écrans noirs).

    ``socket_hint`` : restreint aux processus de CE player (le chemin du
    socket IPC figure dans leur ligne de commande) — évite de figer le mpv
    d'un autre player hébergé sur la même machine. ``None`` : tous les mpv
    « média » (repli mono-player, ex. mpv trop vieux pour l'IPC).
    """
    found: list[int] = []
    try:
        entries = list(Path("/proc").iterdir())
    except OSError:
        return found
    for entry in entries:
        if not entry.name.isdigit():
            continue
        try:
            cmdline = (entry / "cmdline").read_bytes()
        except OSError:
            continue
        parts = cmdline.decode("utf-8", errors="replace").split("\0")
        if not parts or "mpv" not in parts[0]:
            continue
        if socket_hint is not None and not any(socket_hint in p for p in parts[1:]):
            continue
        if is_video_process_cmdline(parts):
            found.append(int(entry.name))
    return found


def is_video_process_cmdline(parts: list[str]) -> bool:
    """Commande mpv = lecture d'un média ? (ignore les affichages noir fixe)."""
    for part in parts[1:]:
        if not part or part.startswith("--"):
            continue
        if part.startswith("/") or part.startswith("./"):
            return not part.endswith(".png")
        return False
    return False


class ChromiumRenderer:
    """Kiosque Chromium pour les éléments web (en ligne uniquement)."""

    def __init__(self, binary: str = "chromium-browser") -> None:
        self.binary = binary
        self._last_url_pid: int | None = None

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
        self._last_url_pid = process.pid
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

    def hold_paused_frame(
        self,
        check_paused: Callable[[], bool],
        keepalive: Callable[[], None] | None = None,
    ) -> None:
        """Figé par le « Pause » back-office : bloque le rendu courant.

        Le kiosque Chromium est suspendu (SIGSTOP) : la page affichée ne
        bouge plus ; SIGCONT au dégel. Appelé depuis le thread lecture du
        moteur pendant que `play_url` attend dans le thread vidéo.
        """
        pid = self._last_url_pid
        if pid is None:
            return
        try:
            os.kill(pid, signal.SIGSTOP)
        except OSError:
            pass
        try:
            while check_paused():
                if keepalive is not None:
                    keepalive()
                time.sleep(0.2)
        finally:
            try:
                os.kill(pid, signal.SIGCONT)
            except OSError:
                pass


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

    def play_url(self, url: str, timeout_seconds: float | None = None) -> None:
        self.events.append(("url", url))
        self._status({"kind": "url", "path": url, "state": "playing"})
        self._sleep(timeout_seconds if timeout_seconds is not None else 1.0)

    def blank(self) -> None:
        self.events.append(("blank", None))
        self._blanked = True
        self._status({"state": "blank", "media_id": None})

    def unblank(self) -> None:
        self.events.append(("unblank", None))
        self._blanked = False

    def hold_paused_frame(
        self,
        check_paused: Callable[[], bool],
        keepalive: Callable[[], None] | None = None,
    ) -> None:
        self.events.append(("hold-paused", None))
        while check_paused():
            self._sleep(0.2)


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
