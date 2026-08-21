from __future__ import annotations

import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from elyon_playback.renderers import is_hung, touch_heartbeat


class Supervisor:
    """Surveille le processus moteur et le redémarre s'il bloque ou meurt.

    Le moteur touche un fichier heartbeat entre chaque élément de playlist ;
    si le fichier dépasse `hung_threshold_seconds` d'âge, le moteur est
    considéré bloqué (mpv figé, GPU bloqué) et tué puis relancé.
    """

    def __init__(
        self,
        command: list[str],
        heartbeat_file: Path,
        hung_threshold_seconds: float = 120.0,
        restart_delay_seconds: float = 3.0,
        max_restarts_per_hour: int = 10,
        now_fn: Callable[[], float] = time.time,
        sleep_fn: Callable[[float], None] = time.sleep,
        log_fn: Callable[[str], None] = print,
    ) -> None:
        self.command = command
        self.heartbeat_file = heartbeat_file
        self.hung_threshold_seconds = hung_threshold_seconds
        self.restart_delay_seconds = restart_delay_seconds
        self.max_restarts_per_hour = max_restarts_per_hour
        self.now_fn = now_fn
        self.sleep_fn = sleep_fn
        self.log_fn = log_fn
        self.restarts: list[float] = []
        self.process: subprocess.Popen[bytes] | None = None

    def _record_restart(self) -> None:
        now = self.now_fn()
        self.restarts = [t for t in self.restarts if now - t < 3600]
        self.restarts.append(now)

    def _too_many_restarts(self) -> bool:
        now = self.now_fn()
        recent = [t for t in self.restarts if now - t < 3600]
        self.restarts = recent
        return len(recent) >= self.max_restarts_per_hour

    def start(self) -> subprocess.Popen[bytes]:
        touch_heartbeat(self.heartbeat_file)
        self.process = subprocess.Popen(self.command)  # noqa: S603
        return self.process

    def step(self) -> bool:
        """Une itération de surveillance ; retourne False si arrêt définitif."""
        process = self.process
        if process is None:
            self.start()
            return True

        if process.poll() is not None:
            self.log_fn(f"[supervisor] moteur terminé (code {process.returncode})")
            if self._too_many_restarts():
                self.log_fn("[supervisor] trop de redémarrages — abandon")
                return False
            self._record_restart()
            self.sleep_fn(self.restart_delay_seconds)
            self.start()
            return True

        if is_hung(self.heartbeat_file, self.hung_threshold_seconds, now=self.now_fn()):
            self.log_fn("[supervisor] moteur bloqué (heartbeat périmé) — kill + restart")
            process.kill()
            process.wait(timeout=10)
            if self._too_many_restarts():
                self.log_fn("[supervisor] trop de redémarrages — abandon")
                return False
            self._record_restart()
            self.sleep_fn(self.restart_delay_seconds)
            self.start()
        return True

    def run_forever(self, poll_interval_seconds: float = 10.0) -> None:
        self.start()
        while self.step():
            self.sleep_fn(poll_interval_seconds)


def main() -> None:
    """Superviseur CLI : elyon-playback-supervisor <data_dir>."""
    data_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/var/lib/elyon-player")
    heartbeat = data_dir / "playback.heartbeat"
    command = [sys.executable, "-m", "elyon_playback.engine", str(data_dir)]
    supervisor = Supervisor(command=command, heartbeat_file=heartbeat)
    supervisor.run_forever()


if __name__ == "__main__":
    main()
