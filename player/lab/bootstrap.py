#!/usr/bin/env python3
"""Provisionne un lab Elyon : org, site, jetons, approbation, contenu, publish.

Destiné aux Raspberry Pi émulés (`make lab`). Idempotent.
"""

from __future__ import annotations

import argparse
import http.cookiejar
import io
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

PNG_1PX = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

DEFAULT_EMAIL = "admin@elyon.local"
DEFAULT_PASSWORD = "elyon-lab-pass"
DEFAULT_ORG_ADMIN = "orgadmin@lab.elyon"


class LabError(RuntimeError):
    """Échec de provisionnement du lab."""


@dataclass
class LabResponse:
    status: int
    body: bytes

    def json(self) -> Any:
        if not self.body:
            return None
        return json.loads(self.body.decode("utf-8"))


def demo_image_bytes() -> bytes:
    """Image de démo lisible sur le mur VNC (Pillow si dispo)."""
    try:
        from PIL import Image, ImageDraw

        img = Image.new("RGB", (960, 540), (15, 23, 42))
        draw = ImageDraw.Draw(img)
        draw.rectangle([24, 24, 935, 515], outline=(56, 189, 248), width=8)
        draw.rectangle([80, 180, 880, 360], fill=(30, 64, 175))
        draw.text((120, 240), "ELYON", fill=(226, 232, 240))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        return buf.getvalue()
    except (OSError, ImportError, ValueError):
        return PNG_1PX


@dataclass
class PlayerSpec:
    serial: str
    name: str
    code_path: Path
    is_preview: bool = False


@dataclass
class LabSpec:
    admin_email: str = DEFAULT_EMAIL
    admin_password: str = DEFAULT_PASSWORD
    org_name: str = "Elyon Lab"
    org_slug: str = "elyon-lab"
    org_admin_email: str = DEFAULT_ORG_ADMIN
    site_name: str = "Hall émulé"
    players: list[PlayerSpec] = field(default_factory=list)
    enroll_ttl_seconds: int = 86400
    wait_devices_seconds: int = 180
    wait_media_seconds: int = 120


class HttpLabApi:
    """Client HTTP stdlib avec cookies + CSRF (appel réel à l'API)."""

    def __init__(self, base_url: str, timeout: float = 20.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.csrf = ""

    def _refresh_csrf(self) -> None:
        for cookie in self.jar:
            if cookie.name == "elyon_csrf":
                self.csrf = cookie.value

    def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        params: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> LabResponse:
        url = f"{self.base_url}{path}"
        if params:
            url = f"{url}?{urllib.parse.urlencode(params)}"
        headers = {"Accept": "application/json"}
        data: bytes | None = None
        if files is not None:
            data, content_type = _encode_multipart(files, json_body if isinstance(json_body, dict) else None)
            headers["Content-Type"] = content_type
        elif json_body is not None:
            data = json.dumps(json_body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if method.upper() not in {"GET", "HEAD"} and self.csrf:
            headers["X-CSRF-Token"] = self.csrf
        request = urllib.request.Request(url, data=data, method=method.upper(), headers=headers)
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                raw = response.read()
                status = int(response.status)
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = int(exc.code)
        self._refresh_csrf()
        return LabResponse(status, raw)


def _encode_multipart(
    files: dict[str, tuple[str, bytes, str]],
    fields: dict[str, str] | None = None,
) -> tuple[bytes, str]:
    boundary = "----ElyonLabBoundary"
    chunks: list[bytes] = []
    for name, value in (fields or {}).items():
        chunks.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode()
        )
    for field_name, (filename, content, content_type) in files.items():
        header = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
        chunks.append(header + content + b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def expect(response: LabResponse, *ok: int, context: str) -> Any:
    if response.status not in ok:
        detail = response.body.decode("utf-8", errors="replace")[:500]
        raise LabError(f"{context} : HTTP {response.status} — {detail}")
    return response.json()


def wait_health(api: HttpLabApi, timeout: float = 90.0) -> None:
    deadline = time.monotonic() + timeout
    last_error = "timeout"
    while time.monotonic() < deadline:
        try:
            response = api.request("GET", "/healthz")
            if response.status == 200:
                return
            last_error = f"HTTP {response.status}"
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = str(exc)
        time.sleep(1)
    raise LabError(f"API injoignable ({last_error})")


def _find(items: list[dict[str, Any]], key: str, value: str) -> dict[str, Any] | None:
    return next((item for item in items if item.get(key) == value), None)


def provision_lab(
    api: Any,
    spec: LabSpec,
    *,
    sleep_fn: Any = time.sleep,
    now_fn: Any = time.monotonic,
    process_uploaded: Any = None,
    enroll_players: Any = None,
    wait_healthz: bool = False,
    log: Any = print,
) -> dict[str, Any]:
    """Crée (ou réutilise) org/site/players/contenu et publie un manifeste."""
    if wait_healthz:
        wait_health(api)

    boot = api.request(
        "POST",
        "/api/auth/bootstrap",
        json_body={"email": spec.admin_email, "password": spec.admin_password},
    )
    if boot.status not in (201, 403):
        expect(boot, 201, context="bootstrap superadmin")

    login = api.request(
        "POST",
        "/api/auth/login",
        json_body={"email": spec.admin_email, "password": spec.admin_password},
    )
    expect(login, 200, context="login superadmin")

    orgs = expect(api.request("GET", "/api/organizations"), 200, context="liste organisations")
    org = _find(orgs, "slug", spec.org_slug)
    if org is None:
        created = api.request(
            "POST",
            "/api/organizations",
            params={"name": spec.org_name, "slug": spec.org_slug},
        )
        org = expect(created, 201, context="création organisation")
    log(f"[lab] organisation {org['name']} ({org['id']})")

    users = expect(api.request("GET", "/api/users"), 200, context="liste utilisateurs")
    if _find(users, "email", spec.org_admin_email) is None:
        created_user = api.request(
            "POST",
            "/api/users",
            json_body={
                "email": spec.org_admin_email,
                "password": spec.admin_password,
                "full_name": "Admin Lab",
                "role": "org_admin",
                "org_id": org["id"],
            },
        )
        expect(created_user, 201, context="création org_admin")

    login_org = api.request(
        "POST",
        "/api/auth/login",
        json_body={"email": spec.org_admin_email, "password": spec.admin_password},
    )
    expect(login_org, 200, context="login org_admin")

    sites = expect(api.request("GET", "/api/sites"), 200, context="liste sites")
    site = _find(sites, "name", spec.site_name)
    if site is None:
        created_site = api.request("POST", "/api/sites", json_body={"name": spec.site_name})
        site = expect(created_site, 201, context="création site")
    log(f"[lab] site {site['name']} ({site['id']})")

    devices = expect(api.request("GET", "/api/devices"), 200, context="liste devices")
    by_serial = {d["serial"]: d for d in devices}
    for player in spec.players:
        existing = by_serial.get(player.serial)
        if existing is not None:
            log(f"[lab] player {player.serial} déjà enrôlé ({existing['status']})")
            continue
        token = api.request(
            "POST",
            "/api/enroll/tokens",
            params={"site_id": site["id"], "ttl_seconds": str(spec.enroll_ttl_seconds)},
        )
        payload = expect(token, 201, context=f"jeton {player.serial}")
        player.code_path.parent.mkdir(parents=True, exist_ok=True)
        player.code_path.write_text(payload["code"] + "\n", encoding="utf-8")
        log(f"[lab] code {player.serial} → {player.code_path}")

    if enroll_players is not None:
        enroll_players(spec)

    if spec.players and spec.wait_devices_seconds > 0:
        deadline = now_fn() + spec.wait_devices_seconds
        wanted = {p.serial for p in spec.players}
        while now_fn() < deadline:
            devices = expect(api.request("GET", "/api/devices"), 200, context="poll devices")
            found = {d["serial"] for d in devices}
            if wanted <= found:
                break
            sleep_fn(2)
        else:
            missing = wanted - {d["serial"] for d in devices}
            raise LabError(f"Players non enrôlés : {', '.join(sorted(missing))}")

    devices = expect(api.request("GET", "/api/devices"), 200, context="devices finaux")
    screens = expect(
        api.request("GET", f"/api/sites/{site['id']}/screens"),
        200,
        context="liste écrans",
    )
    published = []
    for player in spec.players:
        device = _find(devices, "serial", player.serial)
        if device is None:
            raise LabError(f"Device {player.serial} introuvable après attente")
        if device["status"] == "pending":
            approved = api.request("POST", f"/api/devices/{device['id']}/approve")
            expect(approved, 200, context=f"approbation {player.serial}")
            log(f"[lab] approuvé {player.serial}")
        screen_name = f"Écran {player.name}"
        screen = _find(screens, "name", screen_name)
        if screen is None:
            created_screen = api.request(
                "POST",
                f"/api/sites/{site['id']}/screens",
                json_body={"name": screen_name, "device_id": device["id"]},
            )
            expect(created_screen, 201, context=f"écran {player.serial}")
        elif not screen.get("device_id"):
            patched = api.request(
                "PATCH",
                f"/api/screens/{screen['id']}",
                json_body={"device_id": device["id"]},
            )
            expect(patched, 200, context=f"affectation écran {player.serial}")
        if player.is_preview:
            flagged = api.request(
                "PATCH",
                f"/api/devices/{device['id']}",
                json_body={"is_preview": True},
            )
            expect(flagged, 200, context=f"marqueur aperçu {player.serial}")
            log(f"[lab] aperçu admin {player.serial} (brouillon live, sans Publier)")
            continue
        published.append(device["id"])

    media_list = expect(api.request("GET", "/api/media"), 200, context="liste médias")
    demo = _find(media_list, "name", "Lab demo")
    if demo is None:
        uploaded = api.request(
            "POST",
            "/api/media",
            params={"name": "Lab demo"},
            files={"file": ("lab.png", demo_image_bytes(), "image/png")},
        )
        demo = expect(uploaded, 201, context="upload média demo")
        if process_uploaded is not None:
            process_uploaded(demo["id"])
    if spec.wait_media_seconds > 0:
        deadline = now_fn() + spec.wait_media_seconds
        while now_fn() < deadline:
            current = expect(
                api.request("GET", f"/api/media/{demo['id']}"),
                200,
                context="poll média",
            )
            if current.get("status") == "ready":
                demo = current
                break
            sleep_fn(1)
        else:
            raise LabError(f"Média demo non prêt (status={demo.get('status')})")

    playlists = expect(api.request("GET", "/api/playlists"), 200, context="liste playlists")
    playlist = _find(playlists, "name", "Boucle lab")
    if playlist is None:
        created_pl = api.request("POST", "/api/playlists", json_body={"name": "Boucle lab"})
        playlist = expect(created_pl, 201, context="création playlist")
        item = api.request(
            "POST",
            f"/api/playlists/{playlist['id']}/items",
            json_body={"media_id": demo["id"], "duration_seconds": 8},
        )
        expect(item, 201, context="item playlist")

    schedules = expect(api.request("GET", "/api/schedules"), 200, context="liste plannings")
    schedule = _find(schedules, "name", "Permanente lab")
    if schedule is None:
        created_sc = api.request(
            "POST",
            "/api/schedules",
            json_body={
                "site_id": site["id"],
                "playlist_id": playlist["id"],
                "name": "Permanente lab",
                "start_at": "2020-01-01T00:00:00Z",
                "end_at": "2099-01-01T00:00:00Z",
                "priority": 0,
            },
        )
        schedule = expect(created_sc, 201, context="création planning")
    elif not schedule.get("is_active", True):
        reactivated = api.request(
            "PATCH",
            f"/api/schedules/{schedule['id']}",
            json_body={"is_active": True},
        )
        schedule = expect(reactivated, 200, context="réactivation planning")
        log("[lab] planning Permanente lab réactivé")

    for device_id in published:
        excluded = api.request(
            "DELETE",
            f"/api/schedules/{schedule['id']}/exclusions/{device_id}",
        )
        if excluded.status not in (204, 404):
            expect(excluded, 204, context=f"réinitialisation exclusion {device_id}")

    manifests = []
    for device_id in published:
        pub = api.request("POST", f"/api/devices/{device_id}/publish")
        manifests.append(expect(pub, 200, 201, context=f"publish {device_id}"))
        log(f"[lab] publié device {device_id}")

    return {
        "org_id": org["id"],
        "site_id": site["id"],
        "media_id": demo["id"],
        "playlist_id": playlist["id"],
        "device_ids": published,
        "manifests": manifests,
    }


def default_players(
    enroll_dir: Path, count: int, with_preview: bool = False
) -> list[PlayerSpec]:
    players = []
    for index in range(1, count + 1):
        serial = f"emu-rpi-{index}"
        players.append(
            PlayerSpec(
                serial=serial,
                name=f"Raspberry émulé {index}",
                code_path=enroll_dir / f"{serial}.code",
            )
        )
    if with_preview:
        serial = "emu-rpi-preview"
        players.append(
            PlayerSpec(
                serial=serial,
                name="Aperçu administrateur",
                code_path=enroll_dir / f"{serial}.code",
                is_preview=True,
            )
        )
    return players


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Provisionne le lab Raspberry émulé Elyon")
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="URL de l'API")
    parser.add_argument("--enroll-dir", default=".lab/enroll", help="Répertoire des codes")
    parser.add_argument("--players", type=int, default=2, help="Nombre de players émulés")
    parser.add_argument(
        "--preview",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Ajouter le Raspberry d'aperçu admin (emu-rpi-preview)",
    )
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password", default=DEFAULT_PASSWORD)
    args = parser.parse_args(argv)

    enroll_dir = Path(args.enroll_dir)
    enroll_dir.mkdir(parents=True, exist_ok=True)
    spec = LabSpec(
        admin_email=args.email,
        admin_password=args.password,
        players=default_players(enroll_dir, args.players, with_preview=args.preview),
    )
    api = HttpLabApi(args.api)
    try:
        result = provision_lab(api, spec, wait_healthz=True)
    except LabError as exc:
        print(f"[lab] échec : {exc}", file=sys.stderr)
        return 1
    print("[lab] prêt.")
    print("  back-office : http://127.0.0.1:3001")
    print(f"  login       : {spec.org_admin_email} / {spec.admin_password}")
    print(f"  devices     : {', '.join(result['device_ids'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
