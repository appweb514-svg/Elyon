from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

from elyon_agent.state import DeviceState


class AgentError(Exception):
    """Erreur métier de l'agent (API, signature, checksum)."""


@dataclass
class EnrollResult:
    device_id: str
    token: str


@dataclass
class HeartbeatResult:
    server_time: str
    heartbeat_interval_seconds: int


@dataclass
class Command:
    id: str
    type: str
    payload: str | None = None


@dataclass
class Manifest:
    version: int
    payload: str
    signature: str
    published_at: str


@dataclass
class DownloadResult:
    path: Path
    sha256: str
    size_bytes: int
    resumed: bool = False


@dataclass
class DownloadTracker:
    """Suivi de progression optionnel (utilisé par le superviseur)."""

    downloaded: int = 0
    total: int = 0
    on_progress: Any = field(default=None)


class ElyonClient:
    """Client HTTP du player vers l'API centrale.

    `transport` permet d'injecter un transport httpx (tests : ASGITransport).
    """

    def __init__(
        self,
        base_url: str,
        timeout: float = 15.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            base_url=self.base_url, timeout=timeout, transport=transport
        )

    def close(self) -> None:
        try:
            self._client.close()
        except AttributeError:
            # Certains transports de test (ASGITransport) n'exposent pas close().
            pass

    def __enter__(self) -> ElyonClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _device_headers(self, token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def enroll(self, serial: str, name: str, site_code: str) -> EnrollResult:
        response = self._client.post(
            "/api/enroll/request",
            json={"serial": serial, "name": name, "site_code": site_code},
        )
        if response.status_code == 401:
            raise AgentError("Code d'enrôlement invalide ou expiré")
        if response.status_code == 409:
            raise AgentError("Ce player est déjà enrôlé (série connue)")
        response.raise_for_status()
        data = response.json()
        return EnrollResult(device_id=data["device_id"], token=data["token"])

    def fetch_public_key(self) -> str:
        response = self._client.get("/api/server/public-key")
        response.raise_for_status()
        return str(response.json()["public_key_pem"])

    def heartbeat(
        self,
        state: DeviceState,
        player_state: str = "idle",
        current_media_id: str | None = None,
        storage_free_bytes: int | None = None,
        agent_version: str = "0.1.0",
        uptime_seconds: int | None = None,
        load_avg: float | None = None,
        memory_percent: float | None = None,
        cpu_percent: float | None = None,
        lan_ip: str | None = None,
        wifi_ssid: str | None = None,
    ) -> HeartbeatResult:
        response = self._client.post(
            f"/api/devices/{state.device_id}/heartbeat",
            headers=self._device_headers(state.token),
            json={
                "state": player_state,
                "current_media_id": current_media_id,
                "storage_free_bytes": storage_free_bytes,
                "agent_version": agent_version,
                "uptime_seconds": uptime_seconds,
                "load_avg": load_avg,
                "memory_percent": memory_percent,
                "cpu_percent": cpu_percent,
                "lan_ip": lan_ip,
                "wifi_ssid": wifi_ssid,
            },
        )
        if response.status_code in (401, 403):
            raise AgentError(f"Heartbeat refusé ({response.status_code}) : {response.text}")
        response.raise_for_status()
        data = response.json()
        return HeartbeatResult(
            server_time=data["server_time"],
            heartbeat_interval_seconds=data["heartbeat_interval_seconds"],
        )

    def fetch_commands(self, state: DeviceState) -> list[Command]:
        response = self._client.get(
            f"/api/devices/{state.device_id}/commands",
            headers=self._device_headers(state.token),
        )
        if response.status_code in (401, 403):
            raise AgentError(f"Récupération commandes refusée ({response.status_code})")
        response.raise_for_status()
        return [
            Command(id=c["id"], type=c["type"], payload=c.get("payload"))
            for c in response.json()
        ]

    def ack_command(self, state: DeviceState, command_id: str, error: str | None = None) -> None:
        response = self._client.post(
            f"/api/devices/{state.device_id}/commands/{command_id}/ack",
            headers=self._device_headers(state.token),
            json={"error": error},
        )
        response.raise_for_status()

    def fetch_manifest(self, state: DeviceState) -> Manifest:
        response = self._client.get(
            f"/api/devices/{state.device_id}/manifest",
            headers=self._device_headers(state.token),
        )
        if response.status_code == 404:
            raise AgentError("Aucun manifeste publié pour ce player")
        if response.status_code in (401, 403):
            raise AgentError(f"Manifeste refusé ({response.status_code})")
        response.raise_for_status()
        data = response.json()
        return Manifest(
            version=data["version"],
            payload=data["payload"],
            signature=data["signature"],
            published_at=data["published_at"],
        )

    def fetch_widgets_feed(self, state: DeviceState) -> dict[str, Any]:
        """Données des widgets de l'écran (météo, RSS) pour le rendu player."""
        response = self._client.get(
            f"/api/devices/{state.device_id}/widgets",
            headers=self._device_headers(state.token),
        )
        if response.status_code in (401, 403):
            raise AgentError(f"Flux widgets refusé ({response.status_code})")
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else {}

    def download_media(
        self,
        url: str,
        dest: Path,
        expected_sha256: str | None = None,
        expected_size: int | None = None,
        tracker: DownloadTracker | None = None,
        auth_token: str | None = None,
    ) -> DownloadResult:
        """Télécharge un média avec reprise Range, checksum et renommage atomique.

        Écrit vers `dest.part` ; en cas de reprise, le partiel existant est
        complété. Le fichier final n'apparaît qu'une fois complet et vérifié.
        """
        if url.startswith("/"):
            url = f"{self.base_url}{url}"
        part = dest.with_suffix(dest.suffix + ".part")
        part.parent.mkdir(parents=True, exist_ok=True)
        resumed = False
        offset = part.stat().st_size if part.exists() else 0

        headers: dict[str, str] = {}
        if auth_token:
            headers["Authorization"] = f"Bearer {auth_token}"
        if offset > 0:
            headers["Range"] = f"bytes={offset}-"
        response = self._client.get(url, headers=headers)
        if response.status_code == 206:
            resumed = offset > 0
            mode = "ab"
        else:
            response.raise_for_status()
            offset = 0
            mode = "wb"

        hasher = hashlib.sha256()
        if resumed:
            with part.open("rb") as existing:
                for chunk in iter(lambda: existing.read(1024 * 1024), b""):
                    hasher.update(chunk)
        if tracker and response.headers.get("Content-Length"):
            try:
                tracker.total = offset + int(response.headers["Content-Length"])
                tracker.downloaded = offset
            except ValueError:
                pass

        with part.open(mode) as out:
            for chunk in response.iter_bytes(chunk_size=1024 * 1024):
                out.write(chunk)
                hasher.update(chunk)
                if tracker:
                    tracker.downloaded += len(chunk)
            out.flush()
            import os

            os.fsync(out.fileno())

        size = part.stat().st_size
        if expected_size is not None and size != expected_size:
            part.unlink(missing_ok=True)
            raise AgentError(f"Taille invalide : {size} octets (attendu {expected_size})")
        sha256 = hasher.hexdigest()
        if expected_sha256 is not None and sha256 != expected_sha256:
            part.unlink(missing_ok=True)
            raise AgentError("SHA-256 invalide après téléchargement")
        part.replace(dest)
        return DownloadResult(path=dest, sha256=sha256, size_bytes=size, resumed=resumed)

    def download_device_media(
        self,
        media_id: str,
        dest: Path,
        auth_token: str,
        page_index: int | None = None,
    ) -> DownloadResult:
        """Télécharge un média (ou une page PDF) via le point device-file.

        N'importe quel media de l'organisation du player peut être téléchargé
        (indépendamment du manifeste publié) — utilisé par la commande SHOW.
        """
        suffix = f"/pages/{page_index}/device-file" if page_index is not None else "/device-file"
        url = f"/api/media/{media_id}{suffix}"
        return self.download_media(
            url,
            dest,
            expected_sha256=None,
            expected_size=None,
            auth_token=auth_token,
        )

    def verify_manifest(self, manifest: Manifest, public_key_pem: str) -> dict[str, Any]:
        """Vérifie la signature Ed25519 du manifeste et retourne le payload."""
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        try:
            key = serialization.load_pem_public_key(public_key_pem.encode())
            if not isinstance(key, Ed25519PublicKey):
                raise AgentError("Clé publique serveur invalide (Ed25519 attendu)")
            key.verify(base64.b64decode(manifest.signature), manifest.payload.encode())
        except InvalidSignature as exc:
            raise AgentError("Signature du manifeste invalide") from exc
        except (ValueError, TypeError) as exc:
            raise AgentError("Signature du manifeste illisible") from exc
        payload: dict[str, Any] = json.loads(manifest.payload)
        return payload
