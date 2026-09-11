from __future__ import annotations

import errno
import json
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from elyon_agent.client import AgentError, ElyonClient, Manifest
from elyon_agent.state import DeviceState


class SyncError(Exception):
    """Erreur de synchronisation (réseau, checksum, disque)."""


@dataclass
class FileSpec:
    url: str
    sha256: str
    size_bytes: int


@dataclass
class SyncResult:
    version: int
    downloaded: int = 0
    skipped: int = 0
    activated: bool = False
    rolled_back: bool = False
    freed_bytes: int = 0
    errors: list[str] = field(default_factory=list)


def _fsync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


class MediaStore:
    """Stockage local du player : blobs content-addressés + releases activables.

    Structure :
        <root>/blobs/<sha256>               fichiers vérifiés
        <root>/releases/v<version>/         manifeste signé + layout
        <root>/current -> releases/v<ver>   symlink échangé atomiquement
    """

    def __init__(self, root: Path) -> None:
        self.root = root
        self.blobs_dir = root / "blobs"
        self.releases_dir = root / "releases"
        self.current_link = root / "current"
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        self.releases_dir.mkdir(parents=True, exist_ok=True)

    def blob_path(self, sha256: str) -> Path:
        return self.blobs_dir / sha256

    def has_blob(self, spec: FileSpec) -> bool:
        path = self.blob_path(spec.sha256)
        return path.exists() and path.stat().st_size == spec.size_bytes

    def release_path(self, version: int) -> Path:
        return self.releases_dir / f"v{version}"

    def write_release(self, manifest: Manifest, payload: dict[str, Any]) -> Path:
        """Écrit une release (manifeste signé + layout) de façon durable."""
        release = self.release_path(manifest.version)
        if release.exists():
            shutil.rmtree(release)
        release.mkdir(parents=True)
        snapshot = {
            "version": manifest.version,
            "payload": manifest.payload,
            "signature": manifest.signature,
            "published_at": manifest.published_at,
        }
        (release / "manifest.json").write_text(
            json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (release / "layout.json").write_text(
            json.dumps(self.build_layout(payload), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        _fsync_dir(release)
        return release

    @staticmethod
    def build_layout(payload: dict[str, Any]) -> dict[str, Any]:
        """Layout de lecture : associe chaque média à ses blobs locaux."""
        media = []
        for entry in payload.get("media", []):
            if entry["kind"] == "web":
                media.append(
                    {
                        "media_id": entry["media_id"],
                        "name": entry["name"],
                        "kind": "web",
                        "main_blob": "",
                        "page_blobs": [],
                        "url": entry.get("url", ""),
                    }
                )
                continue
            media.append(
                {
                    "media_id": entry["media_id"],
                    "name": entry["name"],
                    "kind": entry["kind"],
                    "main_blob": entry["sha256"],
                    "page_blobs": [p["sha256"] for p in entry.get("page_files", [])],
                }
            )
        return {
            "version": payload.get("published_at"),
            "media": media,
            "blocks": payload.get("blocks", []),
            "widgets": payload.get("widgets") or [],
        }

    def activate(self, release: Path) -> None:
        """Activation atomique : symlink temporaire + rename (résiste à la coupure)."""
        tmp_link = self.root / "current.tmp"
        if tmp_link.is_symlink() or tmp_link.exists():
            tmp_link.unlink()
        os.symlink(os.path.relpath(release, self.root), tmp_link)
        os.replace(tmp_link, self.current_link)
        _fsync_dir(self.root)

    def current_release(self) -> Path | None:
        try:
            return self.current_link.resolve(strict=True)
        except (OSError, RuntimeError):
            return None

    def read_current_layout(self) -> dict[str, Any] | None:
        release = self.current_release()
        if release is None:
            return None
        layout_file = release / "layout.json"
        if not layout_file.exists():
            return None
        layout: dict[str, Any] = json.loads(layout_file.read_text(encoding="utf-8"))
        return layout

    def read_current_manifest(self) -> dict[str, Any] | None:
        release = self.current_release()
        if release is None:
            return None
        manifest_file = release / "manifest.json"
        if not manifest_file.exists():
            return None
        snapshot: dict[str, Any] = json.loads(manifest_file.read_text(encoding="utf-8"))
        return snapshot

    def verify_release(self, layout: dict[str, Any], with_digest: bool = False) -> bool:
        """Vérifie que tous les blobs référencés par une release sont présents."""
        for entry in layout.get("media", []):
            for sha in [entry["main_blob"], *entry.get("page_blobs", [])]:
                blob = self.blob_path(sha)
                if not blob.exists():
                    return False
                if with_digest:
                    import hashlib

                    digest = hashlib.sha256(blob.read_bytes()).hexdigest()
                    if digest != sha:
                        return False
        return True

    def list_releases(self) -> list[Path]:
        if not self.releases_dir.exists():
            return []
        releases = [p for p in self.releases_dir.iterdir() if p.is_dir()]
        return sorted(releases, key=lambda p: _release_version(p.name))

    def gc(self, keep_shas: set[str], keep_releases: int = 2) -> int:
        """Supprime blobs non référencés et releases anciennes ; retourne octets libérés."""
        freed = 0
        keep_release_paths = {p.resolve() for p in self.list_releases()[-keep_releases:]}
        current = self.current_release()
        if current is not None:
            keep_release_paths.add(current.resolve())
        for release in self.list_releases():
            if release.resolve() in keep_release_paths:
                continue
            freed += _tree_size(release)
            shutil.rmtree(release, ignore_errors=True)
        for blob in self.blobs_dir.iterdir():
            if blob.name in keep_shas or blob.name.endswith(".part"):
                continue
            size = blob.stat().st_size
            blob.unlink(missing_ok=True)
            freed += size
        return freed


def _release_version(name: str) -> int:
    try:
        return int(name.removeprefix("v"))
    except ValueError:
        return -1


def _tree_size(path: Path) -> int:
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


class Synchronizer:
    """Synchronisation résiliente : download → release → activation → GC."""

    def __init__(
        self,
        client: ElyonClient,
        store: MediaStore,
        state: DeviceState,
        max_retries: int = 2,
        sleep_fn: Callable[[float], None] = time.sleep,
    ) -> None:
        self.client = client
        self.store = store
        self.state = state
        self.max_retries = max_retries
        self.sleep_fn = sleep_fn

    def needed_files(self, payload: dict[str, Any]) -> dict[str, FileSpec]:
        """Mappe sha256 → spécification pour chaque fichier du manifeste."""
        needed: dict[str, FileSpec] = {}
        for entry in payload.get("media", []):
            if entry.get("kind") == "web":
                continue
            needed[entry["sha256"]] = FileSpec(
                url=entry["url"], sha256=entry["sha256"], size_bytes=entry["size_bytes"]
            )
            for page in entry.get("page_files", []):
                needed[page["sha256"]] = FileSpec(
                    url=page["url"], sha256=page["sha256"], size_bytes=page["size_bytes"]
                )
        return needed

    def check_disk_space(self, specs: list[FileSpec]) -> None:
        usage = shutil.disk_usage(self.store.root)
        missing = sum(s.size_bytes for s in specs)
        if usage.free < missing:
            raise SyncError(
                f"Espace disque insuffisant : {usage.free} octets libres, "
                f"{missing} octets requis"
            )

    def download_all(self, specs: list[FileSpec]) -> tuple[int, int]:
        """Télécharge les blobs manquants avec reprise et retry/backoff."""
        downloaded = 0
        skipped = 0
        for spec in specs:
            if self.store.has_blob(spec):
                skipped += 1
                continue
            self._download_with_retry(spec)
            downloaded += 1
        return downloaded, skipped

    def _download_with_retry(self, spec: FileSpec) -> None:
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                self.client.download_media(
                    spec.url,
                    self.store.blob_path(spec.sha256),
                    expected_sha256=spec.sha256,
                    expected_size=spec.size_bytes,
                    auth_token=self.state.token,
                )
                return
            except AgentError as exc:
                last_error = exc
            except OSError as exc:
                if exc.errno == errno.ENOSPC:
                    raise SyncError(
                        f"Disque plein pendant le téléchargement ({spec.sha256[:12]})"
                    ) from exc
                last_error = exc
            if attempt < self.max_retries:
                self.sleep_fn(2**attempt)
        raise SyncError(f"Téléchargement en échec ({spec.sha256[:12]}) : {last_error}")

    def sync(self, manifest: Manifest, payload: dict[str, Any]) -> SyncResult:
        """Synchronisation complète d'un manifeste vérifié."""
        result = SyncResult(version=manifest.version)
        needed = self.needed_files(payload)
        specs = list(needed.values())

        try:
            self.check_disk_space(
                [s for s in specs if not self.store.has_blob(s)]
            )
            downloaded, skipped = self.download_all(specs)
            result.downloaded = downloaded
            result.skipped = skipped

            release = self.store.write_release(manifest, payload)
            self.store.activate(release)
            result.activated = True

            result.freed_bytes = self.store.gc(keep_shas=set(needed.keys()))
        except SyncError:
            result.rolled_back = True
            raise
        return result

    def recover(self) -> dict[str, Any] | None:
        """Redémarrage : valide la release courante ou retombe sur la précédente."""
        layout = self.store.read_current_layout()
        if layout is not None and self.store.verify_release(layout):
            return layout
        for release in reversed(self.store.list_releases()):
            layout_file = release / "layout.json"
            if not layout_file.exists():
                continue
            candidate: dict[str, Any] = json.loads(layout_file.read_text(encoding="utf-8"))
            if self.store.verify_release(candidate):
                self.store.activate(release)
                return candidate
        return None


def storage_free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def system_telemetry(data_dir: Path) -> dict[str, Any]:
    """Métriques système du player (uptime, charge, mémoire, CPU, IP LAN).

    Chaque valeur est `None` quand elle ne peut pas être lue (ne jamais
    affirmer ce qu'on ne sait pas). Invoqué à chaque heartbeat.
    """
    uptime_seconds: int | None = None
    load_avg: float | None = None
    memory_percent: float | None = None
    cpu_percent: float | None = None

    try:
        with open("/proc/uptime", encoding="utf-8") as f:
            uptime_seconds = int(float(f.read().split()[0]))
    except (OSError, ValueError, IndexError):
        pass
    try:
        with open("/proc/loadavg", encoding="utf-8") as f:
            load_avg = float(f.read().split()[0])
    except (OSError, ValueError, IndexError):
        pass
    try:
        total = 0
        free = 0
        with open("/proc/meminfo", encoding="utf-8") as f:
            for line in f:
                key, _, value = line.partition(":")
                val = int(value.split()[0])
                if key == "MemTotal":
                    total = val
                elif key == "MemAvailable":
                    free = val
        if total:
            memory_percent = round((1 - free / total) * 100, 1)
    except (OSError, ValueError):
        pass
    try:
        cpu = _read_cpu_percent()
        if cpu is not None:
            cpu_percent = cpu
    except Exception:  # noqa: BLE001
        pass

    return {
        "uptime_seconds": uptime_seconds,
        "load_avg": load_avg,
        "memory_percent": memory_percent,
        "cpu_percent": cpu_percent,
        "lan_ip": _lan_ip(),
        "wifi_ssid": _wifi_ssid(),
        "storage_free_bytes": storage_free_bytes(data_dir),
    }


_cpu_sample: dict[str, float] = {}


def _read_cpu_percent() -> float | None:
    """Consommation CPU depuis le dernier appel (échantillon /proc/stat)."""
    global _cpu_sample
    try:
        with open("/proc/stat", encoding="utf-8") as f:
            first = f.readline().split()
    except OSError:
        return None
    if not first or first[0] != "cpu":
        return None
    vals = [float(v) for v in first[1:]]
    idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
    total = sum(vals)
    prev = _cpu_sample
    _cpu_sample = {"idle": idle, "total": total}
    if not prev or total <= prev["total"]:
        return None
    idle_delta = idle - prev["idle"]
    total_delta = total - prev["total"]
    return round(max(0.0, 1 - idle_delta / total_delta) * 100, 1)


def _lan_ip() -> str | None:
    """IP LAN du player (la première adresse IPv4 non-loopback)."""
    import socket

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("10.255.255.255", 1))  # n'envoie rien (UDP)
            address = s.getsockname()[0]
            return address if isinstance(address, str) else None
        finally:
            s.close()
    except OSError:
        return None


def _wifi_ssid() -> str | None:
    """SSID Wi-Fi courant, si lisible (Linux)."""
    try:
        import subprocess

        out = subprocess.run(
            ["iwgetid", "-r"], capture_output=True, timeout=3, check=False
        )
        ssid = out.stdout.decode().strip()
        return ssid or None
    except (OSError, subprocess.TimeoutExpired):
        return None


def sync_from_manifest(
    client: ElyonClient,
    store: MediaStore,
    state: DeviceState,
    manifest: Manifest,
    public_key_pem: str,
    max_retries: int = 2,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> SyncResult:
    """Vérifie la signature puis synchronise (point d'entrée du run loop)."""
    payload = client.verify_manifest(manifest, public_key_pem)
    synchronizer = Synchronizer(
        client, store, state, max_retries=max_retries, sleep_fn=sleep_fn
    )
    return synchronizer.sync(manifest, payload)
