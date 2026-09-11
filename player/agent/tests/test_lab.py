from __future__ import annotations

import json

import pytest

from elyon_agent.client import Command
from elyon_agent.commands import make_dispatcher
from elyon_agent.run import first_run_wizard, make_show_handler, run_forever
from elyon_agent.state import DeviceState

from .conftest import admin_login, bootstrap_site


def test_headless_enroll_from_env(api, agent, agent_settings):
    admin_login(api)
    _, _, code = bootstrap_site(api)
    agent_settings.serial = "emu-rpi-9"
    agent_settings.name = "Pi émulé"
    agent_settings.enroll_code = code

    def boom(prompt: str = "") -> str:
        raise AssertionError(f"stdin inattendu : {prompt}")

    state = first_run_wizard(agent, agent_settings, input_fn=boom)
    assert state.device_id
    devices = api.get("/api/devices").json()
    device = next(d for d in devices if d["id"] == state.device_id)
    assert device["serial"] == "emu-rpi-9"
    assert device["name"] == "Pi émulé"


def test_enroll_from_code_file(api, agent, agent_settings, tmp_path):
    admin_login(api)
    _, _, code = bootstrap_site(api)
    code_file = tmp_path / "emu-rpi-file.code"
    code_file.write_text(code + "\n", encoding="utf-8")
    agent_settings.serial = "emu-rpi-file"
    agent_settings.name = "Pi fichier"
    agent_settings.enroll_code_file = code_file

    def boom(prompt: str = "") -> str:
        raise AssertionError(f"stdin inattendu : {prompt}")

    state = first_run_wizard(agent, agent_settings, input_fn=boom)
    assert DeviceState.load(agent_settings.state_file) is not None
    assert state.device_id


def test_file_command_handlers(tmp_path):
    dispatcher = make_dispatcher(data_dir=tmp_path)
    assert dispatcher.execute(Command(id="1", type="blank")) is None
    assert (tmp_path / "blank").exists()

    (tmp_path / "now-playing.json").write_text('{"media_id": "m1"}', encoding="utf-8")
    assert dispatcher.execute(Command(id="2", type="capture")) is None
    captures = list((tmp_path / "captures").glob("*.json"))
    assert len(captures) == 1
    assert "m1" in captures[0].read_text(encoding="utf-8")

    assert dispatcher.execute(Command(id="3", type="unblank")) is None
    assert not (tmp_path / "blank").exists()

    assert dispatcher.execute(Command(id="4", type="resync")) is None
    assert (tmp_path / "resync-requested").exists()

    with pytest.raises(SystemExit):
        dispatcher.execute(Command(id="5", type="reboot"))
    assert (tmp_path / "reboot-requested").exists()


def test_show_handler_downloads_and_queues(
    api, agent, api_settings, db_session_factory, enrolled, tmp_path, agent_settings
):
    """La commande SHOW télécharge le média puis alimente la file du moteur."""
    import io

    from elyon_api.models import Media
    from elyon_api.services.media_processing import process_media
    from elyon_api.services.storage import LocalStorage
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (64, 36), (200, 30, 30)).save(buf, "PNG")
    content = buf.getvalue()

    org_id, site_id, device_id, token = enrolled
    admin_login(api)
    api.post(
        "/api/media",
        files={"file": ("spot.png", content, "image/png")},
        headers={"X-CSRF-Token": api.cookies.get("elyon_csrf", "")},
    )
    media = api.get("/api/media").json()[0]
    with db_session_factory() as session:
        stored = session.get(Media, media["id"])
        process_media(stored, api_settings, LocalStorage(api_settings.media_storage_root))
        session.commit()

    agent_settings.data_dir = tmp_path
    state = DeviceState(device_id=device_id, token=token)
    handler = make_show_handler(agent, state, tmp_path)
    payload = json.dumps({"media_id": media["id"], "kind": "image"})
    handler(Command(id="show-1", type="show", payload=payload))

    spec = json.loads((tmp_path / "show" / "request.json").read_text(encoding="utf-8"))
    assert spec["media_id"] == media["id"]
    blob = tmp_path / "show" / media["id"]
    assert blob.read_bytes() == content


def test_show_handler_downloads_all_pdf_pages(
    api, agent, api_settings, db_session_factory, enrolled, tmp_path, agent_settings
):
    """SHOW d'un PDF multi-pages : TOUTES les pages sont téléchargées.

    La spec `kind=pages` liste les blobs de chaque page — le moteur les
    déroulera page par page au lieu d'afficher seulement la première.
    """
    agent_settings.data_dir = tmp_path
    state = DeviceState(device_id="dev-multipage", token="tok")
    handler = make_show_handler(agent, state, tmp_path)

    # Fake client : capture les téléchargements et écrit un blob par page.
    downloads: list[tuple[str, int]] = []

    def fake_download(
        media_id: str, dest, auth_token: str, page_index: int | None = None
    ):  # noqa: ANN001
        downloads.append((media_id, page_index if page_index is not None else -1))
        dest.write_bytes(f"page-{page_index}".encode())

    # Le handler appelle agent.download_device_media : remplaçons la méthode.
    agent.download_device_media = fake_download  # type: ignore[method-assign]

    payload = json.dumps(
        {"media_id": "doc123", "kind": "pdf", "pages": 3, "name": "Rapport"}
    )
    handler(Command(id="show-pdf", type="show", payload=payload))

    assert downloads == [("doc123", 0), ("doc123", 1), ("doc123", 2)]
    spec = json.loads((tmp_path / "show" / "request.json").read_text(encoding="utf-8"))
    assert spec["kind"] == "pages"
    assert spec["media_id"] == "doc123"
    assert len(spec["page_blobs"]) == 3
    for index in range(3):
        blob = tmp_path / "show" / f"doc123.p{index}"
        assert blob.exists() and blob.stat().st_size > 0
    # La pause est levée par un nouveau SHOW.
    assert not (tmp_path / "pause").exists()

    # Un PDF d'une SEULE page reste un affichage image simple (page 0).
    payload_single = json.dumps({"media_id": "doc1", "kind": "pdf", "pages": 1})
    handler(Command(id="show-pdf1", type="show", payload=payload_single))
    spec1 = json.loads((tmp_path / "show" / "request.json").read_text(encoding="utf-8"))
    assert spec1["kind"] == "image"
    assert downloads[-1] == ("doc1", 0)


def test_run_forever_passes_synchronizer(monkeypatch, agent, agent_settings, enrolled):
    _, _, device_id, token = enrolled
    DeviceState(device_id=device_id, token=token).save(agent_settings.state_file)
    captured: dict[str, object] = {}

    def fake_loop(client, state, settings, dispatcher, on_manifest=None, synchronizer=None):
        captured["synchronizer"] = synchronizer
        raise KeyboardInterrupt()

    monkeypatch.setattr("elyon_agent.run.agent_loop_once", fake_loop)
    with pytest.raises(KeyboardInterrupt):
        run_forever(agent, agent_settings, sleep_fn=lambda _s: None)
    assert captured["synchronizer"] is not None


def test_file_command_handlers_stop_show(tmp_path):
    dispatcher = make_dispatcher(data_dir=tmp_path)
    media_file = tmp_path / "show" / "m1"
    media_file.parent.mkdir()
    media_file.write_bytes(b"data")
    (tmp_path / "show" / "request.json").write_text(
        '{"media_id": "m1", "kind": "image"}', encoding="utf-8"
    )

    command = Command(id="s1", type="stop_show", payload='{"media_id": "m1"}')
    assert dispatcher.execute(command) is None
    assert not (tmp_path / "show" / "request.json").exists()
    assert not media_file.exists()
