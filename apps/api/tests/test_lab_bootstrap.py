"""Provisionnement du lab Raspberry émulé contre l'API (TestClient)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from elyon_api.models import Media
from elyon_api.services.media_processing import process_media
from elyon_api.services.storage import LocalStorage
from tests.conftest import csrf_headers

ROOT = Path(__file__).resolve().parents[3]
_SPEC = importlib.util.spec_from_file_location(
    "lab_bootstrap", ROOT / "player" / "lab" / "bootstrap.py"
)
assert _SPEC is not None and _SPEC.loader is not None
bootstrap = importlib.util.module_from_spec(_SPEC)
sys.modules["lab_bootstrap"] = bootstrap
_SPEC.loader.exec_module(bootstrap)


class LabTestClient:
    def __init__(self, client) -> None:
        self.client = client

    def request(self, method, path, *, json_body=None, params=None, files=None):
        headers = {}
        csrf = self.client.cookies.get("elyon_csrf")
        if csrf and method.upper() not in {"GET", "HEAD"}:
            headers["X-CSRF-Token"] = csrf
        kwargs: dict = {"headers": headers}
        if json_body is not None:
            kwargs["json"] = json_body
        if params is not None:
            kwargs["params"] = params
        if files is not None:
            kwargs["files"] = files
        response = self.client.request(method, path, **kwargs)
        return bootstrap.LabResponse(response.status_code, response.content)


def test_provision_lab_two_emulated_players(client, settings, db_session_factory, tmp_path):
    enroll_dir = tmp_path / "enroll"
    spec = bootstrap.LabSpec(
        players=bootstrap.default_players(enroll_dir, 2),
        wait_devices_seconds=5,
        wait_media_seconds=5,
    )
    api = LabTestClient(client)

    def enroll_players(lab_spec: bootstrap.LabSpec) -> None:
        for player in lab_spec.players:
            code = player.code_path.read_text(encoding="utf-8").strip()
            enrolled = client.post(
                "/api/enroll/request",
                json={"serial": player.serial, "name": player.name, "site_code": code},
            )
            assert enrolled.status_code == 201, enrolled.text

    def process_uploaded(media_id: str) -> None:
        with db_session_factory() as session:
            stored = session.get(Media, media_id)
            process_media(stored, settings, LocalStorage(settings.media_storage_root))
            session.commit()

    result = bootstrap.provision_lab(
        api,
        spec,
        enroll_players=enroll_players,
        process_uploaded=process_uploaded,
        sleep_fn=lambda _s: None,
    )
    assert len(result["device_ids"]) == 2
    assert result["manifests"]
    devices = client.get("/api/devices", headers=csrf_headers(client)).json()
    serials = {d["serial"] for d in devices}
    assert serials == {"emu-rpi-1", "emu-rpi-2"}
    assert all(d["status"] == "approved" for d in devices)
    schedules = client.get("/api/schedules", headers=csrf_headers(client)).json()
    assert next(s for s in schedules if s["name"] == "Permanente lab")["is_active"] is True
