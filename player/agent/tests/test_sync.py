from __future__ import annotations

import json
import os

import pytest
from elyon_api.models import Media

from elyon_agent.client import ElyonClient
from elyon_agent.state import DeviceState
from elyon_agent.sync import MediaStore, SyncError, Synchronizer

from .conftest import csrf_headers
from .test_agent import png_bytes, setup_published_screen


@pytest.fixture()
def store(tmp_path):
    return MediaStore(tmp_path / "player")


@pytest.fixture()
def sync_env(api, agent, api_settings, db_session_factory, store):
    """Player synchronisé une fois : retourne le contexte de test."""
    env = setup_published_screen(api, api_settings, db_session_factory)
    state = DeviceState(device_id=env["device_id"], token=env["token"])
    synchronizer = Synchronizer(agent, store, state)
    manifest = agent.fetch_manifest(state)
    payload = agent.verify_manifest(manifest, agent.fetch_public_key())
    result = synchronizer.sync(manifest, payload)
    assert result.activated
    env.update(
        state=state, synchronizer=synchronizer, manifest=manifest, payload=payload, result=result
    )
    return env


class TestSyncBasics:
    def test_downloads_and_activates(self, sync_env, store, tmp_path):
        env = sync_env
        media_entry = env["payload"]["media"][0]
        sha = media_entry["sha256"]

        assert env["result"].downloaded == 1
        assert store.blob_path(sha).exists()
        assert store.blob_path(sha).read_bytes() == png_bytes()

        current = store.current_release()
        assert current is not None
        assert current.name == "v1"
        assert os.path.islink(store.current_link)

        snapshot = store.read_current_manifest()
        assert snapshot["version"] == 1
        assert snapshot["signature"] == env["manifest"].signature

    def test_layout_references_blobs(self, sync_env, store):
        layout = store.read_current_layout()
        assert layout is not None
        entry = layout["media"][0]
        assert entry["kind"] == "image"
        assert store.blob_path(entry["main_blob"]).exists()
        assert entry["page_blobs"] == []
        assert len(layout["blocks"]) == 1

    def test_build_layout_keeps_widgets(self, store):
        payload = {
            "published_at": "2026-01-01T00:00:00Z",
            "media": [],
            "blocks": [],
            "widgets": [
                {"type": "clock", "position": "bottom-right", "visible": True,
                 "params": {"format": "HH:MM:SS"}},
            ],
        }
        layout = store.build_layout(payload)
        assert layout["widgets"] == payload["widgets"]

    def test_build_layout_widgets_default_empty(self, store):
        layout = store.build_layout({"published_at": "x", "media": [], "blocks": []})
        assert layout["widgets"] == []

    def test_idempotent_second_sync(self, sync_env):
        env = sync_env
        result = env["synchronizer"].sync(env["manifest"], env["payload"])
        assert result.downloaded == 0
        assert result.skipped == 1
        assert result.activated

    def test_resumes_partial_download(self, api, agent, api_settings, db_session_factory, store):
        env = setup_published_screen(api, api_settings, db_session_factory)
        state = DeviceState(device_id=env["device_id"], token=env["token"])
        synchronizer = Synchronizer(agent, store, state)

        media_entry = json.loads(
            agent.fetch_manifest(state).payload
        )["media"][0]
        content = png_bytes()
        part = store.blob_path(media_entry["sha256"]).with_suffix(".part")
        part.write_bytes(content[:10])

        manifest = agent.fetch_manifest(state)
        payload = agent.verify_manifest(manifest, agent.fetch_public_key())
        result = synchronizer.sync(manifest, payload)
        assert result.downloaded == 1
        assert store.blob_path(media_entry["sha256"]).read_bytes() == content
        assert not part.exists()


class TestSyncFailures:
    def test_invalid_checksum_blocks_activation(
        self, api, agent, api_settings, db_session_factory, store
    ):
        """Le serveur sert un fichier corrompu : pas d'activation, blob purgé."""
        env = setup_published_screen(api, api_settings, db_session_factory)
        state = DeviceState(device_id=env["device_id"], token=env["token"])

        manifest = agent.fetch_manifest(state)
        payload = agent.verify_manifest(manifest, agent.fetch_public_key())
        sha = payload["media"][0]["sha256"]

        # Coupure/corruption côté serveur : le contenu ne correspond plus au sha.
        with db_session_factory() as session:
            stored = session.get(Media, env["media"]["id"])
            file_path = api_settings.media_storage_root / stored.storage_path
            file_path.write_bytes(b"CORRUPTED-DATA")

        synchronizer = Synchronizer(agent, store, state)
        with pytest.raises(SyncError, match="SHA-256|Téléchargement"):
            synchronizer.sync(manifest, payload)

        assert store.current_release() is None
        assert not store.blob_path(sha).exists()

    def test_disk_full_before_download(self, sync_env, store, monkeypatch):
        import shutil as shutil_module

        env = sync_env
        store.blob_path(env["payload"]["media"][0]["sha256"]).unlink()

        class FakeUsage:
            free = 10

        monkeypatch.setattr(shutil_module, "disk_usage", lambda path: FakeUsage())
        with pytest.raises(SyncError, match="insuffisant"):
            env["synchronizer"].sync(env["manifest"], env["payload"])

    def test_disk_full_during_download(
        self, api, agent, api_settings, db_session_factory, store, monkeypatch
    ):
        env = setup_published_screen(api, api_settings, db_session_factory)
        state = DeviceState(device_id=env["device_id"], token=env["token"])

        def raise_enospc(*args, **kwargs):
            raise OSError(28, "No space left on device")

        monkeypatch.setattr(ElyonClient, "download_media", raise_enospc)
        synchronizer = Synchronizer(agent, store, state)
        manifest = agent.fetch_manifest(state)
        payload = agent.verify_manifest(manifest, agent.fetch_public_key())
        with pytest.raises(SyncError, match="Disque plein"):
            synchronizer.sync(manifest, payload)
        assert store.current_release() is None

    def test_retry_then_success(
        self, api, agent, api_settings, db_session_factory, store, monkeypatch
    ):
        """Une coupure réseau passagère est rattrapée au retry."""
        env = setup_published_screen(api, api_settings, db_session_factory)
        state = DeviceState(device_id=env["device_id"], token=env["token"])
        manifest = agent.fetch_manifest(state)
        payload = agent.verify_manifest(manifest, agent.fetch_public_key())

        sleeps = []
        original = ElyonClient.download_media
        calls = {"n": 0}

        def flaky(self_client, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise OSError("connection reset")
            return original(self_client, *args, **kwargs)

        monkeypatch.setattr(ElyonClient, "download_media", flaky)
        synchronizer = Synchronizer(agent, store, state, sleep_fn=sleeps.append)
        result = synchronizer.sync(manifest, payload)
        assert result.downloaded == 1
        assert calls["n"] == 2
        assert sleeps == [1]


class TestOfflineRestart:
    def test_current_release_survives_restart(self, sync_env, tmp_path):
        """Redémarrage hors ligne : un nouveau store lit la release courante."""
        env = sync_env
        old_store = env["synchronizer"].store

        new_store = MediaStore(old_store.root)
        layout = new_store.read_current_layout()
        assert layout is not None
        assert new_store.verify_release(layout)
        assert new_store.verify_release(layout, with_digest=True)

        # recover() via un synchronizer minimal (aucun réseau requis)
        class _NoClient:
            pass

        synchronizer = Synchronizer(_NoClient(), new_store, env["state"])
        assert synchronizer.recover() == layout

    def test_rollback_to_previous_release(self, sync_env, store):
        """Release courante corrompue : retombée sur la précédente."""
        env = sync_env

        # Corrompt la release courante (v1) : layout supprimé.
        api_response_layout = store.read_current_layout()
        assert api_response_layout is not None
        (store.current_release() / "layout.json").unlink()

        class _NoClient:
            pass

        recovery = Synchronizer(_NoClient(), store, env["state"])
        assert recovery.recover() is None  # aucune release saine

        # Réécrit un layout valide et vérifie la retombée.
        (store.current_release() / "layout.json").write_text(
            json.dumps(api_response_layout), encoding="utf-8"
        )
        assert recovery.recover() == api_response_layout


class TestGarbageCollection:
    def test_gc_removes_unreferenced_blobs(
        self, api, agent, api_settings, db_session_factory, store
    ):
        """v2 sans média : blob de v1 supprimé, release v2 active."""
        env = setup_published_screen(api, api_settings, db_session_factory)
        state = DeviceState(device_id=env["device_id"], token=env["token"])
        synchronizer = Synchronizer(agent, store, state)

        manifest1 = agent.fetch_manifest(state)
        payload1 = agent.verify_manifest(manifest1, agent.fetch_public_key())
        result1 = synchronizer.sync(manifest1, payload1)
        assert result1.activated
        sha1 = payload1["media"][0]["sha256"]
        assert store.blob_path(sha1).exists()

        # Désactive le planning : le serveur republie automatiquement (v2)
        # sans média ; le publish manuel crée v3, au contenu identique.
        schedule_id = payload1["blocks"][0]["schedule_id"]
        patch = api.patch(
            f"/api/schedules/{schedule_id}",
            json={"is_active": False},
            headers=csrf_headers(api),
        )
        assert patch.status_code == 200, patch.text
        pub2 = api.post(
            f"/api/devices/{env['device_id']}/publish", headers=csrf_headers(api)
        )
        assert pub2.status_code == 200, pub2.text

        manifest2 = agent.fetch_manifest(state)
        payload2 = agent.verify_manifest(manifest2, agent.fetch_public_key())
        assert payload2["media"] == []
        result2 = synchronizer.sync(manifest2, payload2)
        assert result2.activated
        assert result2.freed_bytes > 0

        assert not store.blob_path(sha1).exists()
        assert store.read_current_layout()["media"] == []
        releases = store.list_releases()
        # v2 (républication auto du patch) puis v3 (publish manuel) : le GC ne
        # conserve que les 2 dernières releases.
        assert [p.name for p in releases] == ["v1", "v3"]
