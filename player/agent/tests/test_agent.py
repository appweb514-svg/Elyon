from __future__ import annotations

import datetime as dt
import hashlib
import io
import json
import stat

import pytest
from elyon_api.models import Media
from elyon_api.services.media_processing import process_media
from elyon_api.services.storage import LocalStorage
from fastapi.testclient import TestClient

from elyon_agent.client import AgentError, ElyonClient
from elyon_agent.commands import make_dispatcher
from elyon_agent.run import agent_loop_once, first_run_wizard, pin_server_key
from elyon_agent.state import DeviceState

from .conftest import admin_login, approve_device, bootstrap_site, csrf_headers, enroll_device


@pytest.fixture()
def agent(app, api, agent_settings):
    client = ElyonClient(
        agent_settings.server_url,
        timeout=agent_settings.request_timeout_seconds,
        transport=api._transport,  # noqa: SLF001 — transport de test du TestClient
    )
    yield client
    client.close()


def png_bytes() -> bytes:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def setup_published_screen(api: TestClient, api_settings, db_session_factory) -> dict:
    """Org + site + média prêt + playlist + planning + écran + manifeste publié."""
    admin_login(api)
    org_id, site_id, code = bootstrap_site(api, name="SignCo")
    playlist = api.post(
        "/api/playlists", json={"name": "PL"}, headers=csrf_headers(api)
    ).json()
    media = api.post(
        "/api/media",
        files={"file": ("a.png", png_bytes(), "image/png")},
        headers=csrf_headers(api),
    ).json()
    with db_session_factory() as session:
        stored = session.get(Media, media["id"])
        process_media(stored, api_settings, LocalStorage(api_settings.media_storage_root))
        session.commit()
    api.post(
        f"/api/playlists/{playlist['id']}/items",
        json={"media_id": media["id"], "duration_seconds": 8},
        headers=csrf_headers(api),
    )
    now = dt.datetime.now(dt.UTC)
    api.post(
        "/api/schedules",
        json={
            "site_id": site_id,
            "playlist_id": playlist["id"],
            "name": "Toute la journée",
            "start_at": (now - dt.timedelta(hours=1)).isoformat(),
            "end_at": (now + dt.timedelta(hours=1)).isoformat(),
        },
        headers=csrf_headers(api),
    )
    device = enroll_device(api, code)
    approve_device(api, device["device_id"])
    api.post(
        f"/api/sites/{site_id}/screens",
        json={"name": "Écran", "device_id": device["device_id"]},
        headers=csrf_headers(api),
    )
    pub = api.post(
        f"/api/devices/{device['device_id']}/publish", headers=csrf_headers(api)
    )
    assert pub.status_code == 200, pub.text
    return {
        "device_id": device["device_id"],
        "token": device["token"],
        "media": media,
        "manifest": pub.json(),
    }


class TestEnrollment:
    def test_wizard_enrolls_and_saves_state(self, api, agent, agent_settings):
        admin_login(api)
        _, _, code = bootstrap_site(api)

        inputs = io.StringIO("Hall A\n" + code + "\n")
        state = first_run_wizard(
            agent, agent_settings, input_fn=lambda prompt="": inputs.readline().strip()
        )

        assert state.device_id
        assert state.token
        assert agent_settings.state_file.exists()
        perms = stat.S_IMODE(agent_settings.state_file.stat().st_mode)
        assert perms == 0o600

        devices = api.get("/api/devices").json()
        device = next(d for d in devices if d["id"] == state.device_id)
        assert device["status"] == "pending"

    def test_wizard_rejects_invalid_code(self, api, agent, agent_settings):
        admin_login(api)
        inputs = io.StringIO("Hall A\nINVALID1\n")
        with pytest.raises(AgentError, match="invalide"):
            first_run_wizard(
                agent,
                agent_settings,
                input_fn=lambda prompt="": inputs.readline().strip(),
            )

    def test_state_roundtrip(self, tmp_path, agent_settings):
        state = DeviceState(device_id="d1", token="t1", pinned_public_key="KEY")
        state.save(agent_settings.state_file)
        loaded = DeviceState.load(agent_settings.state_file)
        assert loaded == state


class TestHeartbeat:
    def test_rejected_before_approval(self, api, agent, agent_settings):
        admin_login(api)
        _, _, code = bootstrap_site(api)
        device = enroll_device(api, code)
        state = DeviceState(device_id=device["device_id"], token=device["token"])
        with pytest.raises(AgentError, match="refusé"):
            agent.heartbeat(state)

    def test_ok_after_approval_returns_interval(self, api, agent, enrolled):
        _, _, device_id, token = enrolled
        state = DeviceState(device_id=device_id, token=token)
        result = agent.heartbeat(state, agent_version="test")
        assert result.server_time
        assert result.heartbeat_interval_seconds > 0

        devices = api.get("/api/devices").json()
        device = next(d for d in devices if d["id"] == device_id)
        assert device["last_seen_at"] is not None


class TestCommands:
    def test_fetch_execute_ack(self, api, agent, enrolled):
        _, _, device_id, token = enrolled
        state = DeviceState(device_id=device_id, token=token)
        cmd = api.post(
            f"/api/devices/{device_id}/commands",
            json={"type": "resync"},
            headers=csrf_headers(api),
        )
        assert cmd.status_code == 201, cmd.text
        command_id = cmd.json()["id"]

        commands = agent.fetch_commands(state)
        assert len(commands) == 1
        assert commands[0].type == "resync"

        executed = []
        dispatcher = make_dispatcher({"resync": lambda c: executed.append(c.id)})
        error = dispatcher.execute(commands[0])
        assert error is None
        assert executed == [command_id]
        agent.ack_command(state, command_id)

        commands_after = agent.fetch_commands(state)
        assert commands_after == []

    def test_unsupported_command_acks_error(self, api, agent, enrolled):
        _, _, device_id, token = enrolled
        state = DeviceState(device_id=device_id, token=token)
        cmd = api.post(
            f"/api/devices/{device_id}/commands",
            json={"type": "capture"},
            headers=csrf_headers(api),
        )
        command_id = cmd.json()["id"]

        from elyon_agent.commands import CommandDispatcher

        dispatcher = CommandDispatcher()
        error = dispatcher.execute(
            type("C", (), {"id": command_id, "type": "capture", "payload": None})()
        )
        assert "non supportée" in error
        agent.ack_command(state, command_id, error=error)

        events = api.get("/api/events", params={"device_id": device_id}).json()
        assert any("échouée" in e["message"] for e in events)


class TestManifest:
    def test_fetch_verify(self, api, agent, api_settings, db_session_factory):
        env = setup_published_screen(api, api_settings, db_session_factory)
        state = DeviceState(device_id=env["device_id"], token=env["token"])

        manifest = agent.fetch_manifest(state)
        assert manifest.version == 1

        public_key = agent.fetch_public_key()
        payload = agent.verify_manifest(manifest, public_key)
        assert payload["device_id"] == env["device_id"]
        assert len(payload["blocks"]) == 1
        assert payload["media"][0]["media_id"] == env["media"]["id"]

    def test_tampered_signature_rejected(self, api, agent, api_settings, db_session_factory):
        env = setup_published_screen(api, api_settings, db_session_factory)
        state = DeviceState(device_id=env["device_id"], token=env["token"])

        manifest = agent.fetch_manifest(state)
        manifest.signature = "QUFBQQ=="
        with pytest.raises(AgentError, match="Signature"):
            agent.verify_manifest(manifest, agent.fetch_public_key())

    def test_wrong_key_rejected(self, api, agent, api_settings, db_session_factory):
        env = setup_published_screen(api, api_settings, db_session_factory)
        state = DeviceState(device_id=env["device_id"], token=env["token"])

        manifest = agent.fetch_manifest(state)
        other_key = (
            "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEA\n-----END PUBLIC KEY-----\n"
        )
        with pytest.raises(AgentError):
            agent.verify_manifest(manifest, other_key)

    def test_tofu_pinning_detects_key_change(self, api, agent, enrolled, agent_settings):
        _, _, device_id, token = enrolled
        state = DeviceState(device_id=device_id, token=token, pinned_public_key="ANCIENNE")

        with pytest.raises(RuntimeError, match="changé"):
            pin_server_key(agent, state, agent_settings)

    def test_tofu_pinning_first_use(self, api, agent, enrolled, agent_settings):
        _, _, device_id, token = enrolled
        state = DeviceState(device_id=device_id, token=token)

        key = pin_server_key(agent, state, agent_settings)
        assert key.startswith("-----BEGIN PUBLIC KEY-----")
        assert state.pinned_public_key == key

        saved = DeviceState.load(agent_settings.state_file)
        assert saved is not None and saved.pinned_public_key == key


class TestMediaDownload:
    def test_download_full_and_checksum(
        self, api, agent, api_settings, db_session_factory, tmp_path
    ):
        env = setup_published_screen(api, api_settings, db_session_factory)
        state = DeviceState(device_id=env["device_id"], token=env["token"])

        manifest = agent.fetch_manifest(state)
        payload = json.loads(manifest.payload)
        media_entry = payload["media"][0]
        content = png_bytes()
        assert media_entry["sha256"] == hashlib.sha256(content).hexdigest()

        dest = tmp_path / "media.png"
        result = agent.download_media(
            media_entry["url"], dest, expected_sha256=media_entry["sha256"],
            auth_token=state.token,
        )
        assert dest.read_bytes() == content
        assert result.resumed is False
        assert result.size_bytes == len(content)

    def test_download_resumes_partial(self, api, agent, api_settings, db_session_factory, tmp_path):
        env = setup_published_screen(api, api_settings, db_session_factory)
        state = DeviceState(device_id=env["device_id"], token=env["token"])

        manifest = agent.fetch_manifest(state)
        media_entry = json.loads(manifest.payload)["media"][0]
        content = png_bytes()
        dest = tmp_path / "media.png"
        part = dest.with_suffix(".png.part")
        part.write_bytes(content[:10])

        result = agent.download_media(
            media_entry["url"], dest, expected_sha256=media_entry["sha256"],
            auth_token=state.token,
        )
        assert result.resumed is True
        assert dest.read_bytes() == content
        assert not part.exists()

    def test_download_bad_checksum_raises(
        self, api, agent, api_settings, db_session_factory, tmp_path
    ):
        env = setup_published_screen(api, api_settings, db_session_factory)
        state = DeviceState(device_id=env["device_id"], token=env["token"])

        manifest = agent.fetch_manifest(state)
        media_entry = json.loads(manifest.payload)["media"][0]
        dest = tmp_path / "media.png"

        with pytest.raises(AgentError, match="SHA-256"):
            agent.download_media(
                media_entry["url"], dest, expected_sha256="00" * 32,
                auth_token=state.token,
            )
        assert not dest.exists()
        assert not dest.with_suffix(".png.part").exists()

    def test_download_bad_size_raises(self, api, agent, api_settings, db_session_factory, tmp_path):
        env = setup_published_screen(api, api_settings, db_session_factory)
        state = DeviceState(device_id=env["device_id"], token=env["token"])

        manifest = agent.fetch_manifest(state)
        media_entry = json.loads(manifest.payload)["media"][0]
        dest = tmp_path / "media.png"

        with pytest.raises(AgentError, match="Taille"):
            agent.download_media(
                media_entry["url"], dest, expected_sha256=media_entry["sha256"],
                expected_size=1, auth_token=state.token,
            )


class TestAgentLoop:
    def test_loop_once(self, api, agent, agent_settings, api_settings, db_session_factory):
        env = setup_published_screen(api, api_settings, db_session_factory)
        state = DeviceState(device_id=env["device_id"], token=env["token"])

        received = []
        interval = agent_loop_once(
            agent,
            state,
            agent_settings,
            make_dispatcher(),
            on_manifest=lambda m, p: received.append((m.version, p)),
        )
        assert interval == api_settings.heartbeat_interval_seconds
        assert len(received) == 1
        version, payload = received[0]
        assert version == 1
        assert payload["device_id"] == env["device_id"]

    def test_loop_once_without_manifest(self, api, agent, enrolled, agent_settings):
        _, _, device_id, token = enrolled
        state = DeviceState(device_id=device_id, token=token)
        received = []
        interval = agent_loop_once(
            agent,
            state,
            agent_settings,
            make_dispatcher(),
            on_manifest=lambda m, p: received.append(m),
        )
        assert interval > 0
        assert received == []
