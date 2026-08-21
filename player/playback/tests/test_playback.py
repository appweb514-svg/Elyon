from __future__ import annotations

from pathlib import Path

from elyon_playback.engine import PlaybackEngine, build_queue
from elyon_playback.renderers import (
    BlankState,
    heartbeat_age,
    is_hung,
    touch_heartbeat,
)
from elyon_playback.supervisor import Supervisor


class FakeRenderer:
    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []

    def play_image(self, path: Path, duration_seconds: float) -> None:
        self.events.append(("image", (path, duration_seconds)))

    def play_video(self, path: Path) -> None:
        self.events.append(("video", path))

    def play_url(self, url: str) -> None:
        self.events.append(("url", url))

    def blank(self) -> None:
        self.events.append(("blank", None))

    def unblank(self) -> None:
        self.events.append(("unblank", None))


def make_layout() -> dict:
    return {
        "media": [
            {
                "media_id": "m-img",
                "name": "Logo",
                "kind": "image",
                "main_blob": "aaa",
                "page_blobs": [],
            },
            {
                "media_id": "m-pdf",
                "name": "Doc",
                "kind": "pdf",
                "main_blob": "bbb",
                "page_blobs": ["p1", "p2"],
            },
            {
                "media_id": "m-vid",
                "name": "Spot",
                "kind": "video",
                "main_blob": "ccc",
                "page_blobs": [],
            },
        ],
        "blocks": [
            {
                "schedule_id": "s-low",
                "priority": 0,
                "entries": [
                    {"media_id": "m-img", "duration_seconds": 5},
                ],
            },
            {
                "schedule_id": "s-high",
                "priority": 10,
                "entries": [
                    {"media_id": "m-img", "duration_seconds": 12},
                    {"media_id": "m-pdf", "duration_seconds": 7},
                    {"media_id": "m-vid", "duration_seconds": None},
                    {"media_id": "m-inconnu", "duration_seconds": 9},
                ],
            },
        ],
    }


class TestBuildQueue:
    def test_priority_wins(self, tmp_path):
        items = build_queue(make_layout(), tmp_path)
        # Seul le bloc prioritaire (s-high) est joué : image + 2 pages + vidéo.
        assert len(items) == 4

    def test_item_structure(self, tmp_path):
        items = build_queue(make_layout(), tmp_path)
        image, page1, page2, video = items[0], items[1], items[2], items[3]

        assert image.kind == "image"
        assert image.path == tmp_path / "aaa"
        assert image.duration_seconds == 12.0

        assert page1.kind == "page"
        assert page1.path == tmp_path / "p1"
        assert page1.duration_seconds == 7.0
        assert page1.name == "Doc p.1"
        assert page2.path == tmp_path / "p2"

        assert video.kind == "video"
        assert video.duration_seconds is None

    def test_tie_break_schedule_id_asc(self, tmp_path):
        layout = make_layout()
        # Priorités égales : le plus petit schedule_id l'emporte.
        layout["blocks"][0]["priority"] = 10
        layout["blocks"][0]["schedule_id"] = "s-aaa"
        items = build_queue(layout, tmp_path)
        # Le gagnant est s-aaa (une seule image 5 s), pas s-high.
        assert [i.duration_seconds for i in items] == [5.0]
        assert items[0].media_id == "m-img"

    def test_empty_layout(self, tmp_path):
        assert build_queue({"media": [], "blocks": []}, tmp_path) == []


class TestPlaybackEngine:
    def test_plays_full_queue_then_loops(self, tmp_path):
        renderer = FakeRenderer()
        layout = make_layout()
        layout["blocks"] = [layout["blocks"][1]]  # un seul bloc

        engine = PlaybackEngine(
            renderer=renderer,
            layout_provider=lambda: layout,
            heartbeat_file=tmp_path / "hb",
            blob_dir=tmp_path,
            stop_check=lambda: len(renderer.events) >= 5,
            sleep_fn=lambda s: None,
        )
        engine.run_forever()

        kinds = [e[0] for e in renderer.events]
        # 4 éléments de la file, puis re-boucle sur le premier.
        assert kinds == ["image", "image", "image", "video", "image"]
        assert (tmp_path / "hb").exists()

    def test_blank_pauses_playback(self, tmp_path):
        renderer = FakeRenderer()
        blank_state = BlankState()
        stop_flags = [False]
        steps = {"n": 0}

        def stop_check() -> bool:
            steps["n"] += 1
            if steps["n"] > 4:
                stop_flags[0] = True
            return stop_flags[0]

        engine = PlaybackEngine(
            renderer=renderer,
            layout_provider=lambda: make_layout_with_single_image(),
            heartbeat_file=tmp_path / "hb",
            blob_dir=tmp_path,
            blank_state=blank_state,
            stop_check=stop_check,
            sleep_fn=lambda s: None,
        )
        blank_state.blank()
        engine.run_forever()
        assert renderer.events == [("blank", None)]

    def test_no_layout_idles(self, tmp_path):
        renderer = FakeRenderer()
        stops = iter([False, False, True])
        engine = PlaybackEngine(
            renderer=renderer,
            layout_provider=lambda: None,
            heartbeat_file=tmp_path / "hb",
            blob_dir=tmp_path,
            stop_check=lambda: next(stops),
            sleep_fn=lambda s: None,
        )
        engine.run_forever()
        assert renderer.events == []
        assert engine.current_media_id is None

    def test_current_media_id_tracked(self, tmp_path):
        renderer = FakeRenderer()
        stops = iter([False, False, True])
        engine = PlaybackEngine(
            renderer=renderer,
            layout_provider=lambda: make_layout_with_single_image(),
            heartbeat_file=tmp_path / "hb",
            blob_dir=tmp_path,
            stop_check=lambda: next(stops),
            sleep_fn=lambda s: None,
        )
        engine.run_forever()
        assert engine.current_media_id == "m-img"

    def test_layout_reload_between_iterations(self, tmp_path):
        renderer = FakeRenderer()
        layout_a = make_layout_with_single_image()
        layout_b = {"media": [], "blocks": []}
        provider_states = [layout_a, layout_b]

        def provider():
            return provider_states.pop(0) if provider_states else layout_b

        stops = iter([False, False, False, True])
        engine = PlaybackEngine(
            renderer=renderer,
            layout_provider=provider,
            heartbeat_file=tmp_path / "hb",
            blob_dir=tmp_path,
            stop_check=lambda: next(stops),
            sleep_fn=lambda s: None,
        )
        engine.run_forever()
        assert len(renderer.events) == 1


def make_layout_with_single_image() -> dict:
    return {
        "media": [
            {
                "media_id": "m-img",
                "name": "Logo",
                "kind": "image",
                "main_blob": "aaa",
                "page_blobs": [],
            }
        ],
        "blocks": [
            {
                "schedule_id": "s-1",
                "priority": 5,
                "entries": [{"media_id": "m-img", "duration_seconds": 4}],
            }
        ],
    }


class TestHeartbeatWatchdog:
    def test_touch_and_age(self, tmp_path):
        import time

        hb = tmp_path / "hb"
        touch_heartbeat(hb)
        time.sleep(0.01)
        age = heartbeat_age(hb, now=time.time() + 1.5)
        assert age is not None
        assert 1.0 <= age <= 3.0

    def test_missing_heartbeat(self, tmp_path):
        assert heartbeat_age(tmp_path / "absent") is None
        assert not is_hung(tmp_path / "absent", threshold_seconds=10)

    def test_hung_detection(self, tmp_path):
        hb = tmp_path / "hb"
        hb.write_text("1000.0", encoding="utf-8")
        assert is_hung(hb, threshold_seconds=10, now=1000.0 + 11)
        assert not is_hung(hb, threshold_seconds=10, now=1000.0 + 5)

    def test_corrupt_heartbeat(self, tmp_path):
        hb = tmp_path / "hb"
        hb.write_text("not-a-number", encoding="utf-8")
        assert heartbeat_age(hb) is None


class TestSupervisor:
    def test_starts_and_detects_exit(self, tmp_path):
        hb = tmp_path / "hb"
        commands = []

        class FakeProcess:
            def __init__(self, returncode=None) -> None:
                self.returncode = returncode

            def poll(self):
                return self.returncode

            def kill(self) -> None:
                self.returncode = -9

            def wait(self, timeout=None) -> int:
                return self.returncode if self.returncode is not None else 0

        supervisor = Supervisor(
            command=["echo", "engine"],
            heartbeat_file=hb,
            restart_delay_seconds=0,
            now_fn=lambda: 1000.0,
            sleep_fn=lambda s: None,
            log_fn=lambda msg: commands.append(msg),
        )
        supervisor.process = FakeProcess(returncode=0)
        assert supervisor.step()  # exit détecté → restart
        assert supervisor.process is not None

    def test_hung_engine_restarted(self, tmp_path):
        hb = tmp_path / "hb"
        logs = []

        class FakeProcess:
            def __init__(self) -> None:
                self.returncode = None
                self.killed = False

            def poll(self):
                return None

            def kill(self) -> None:
                self.killed = True
                self.returncode = -9

            def wait(self, timeout=None) -> int:
                return 0

        supervisor = Supervisor(
            command=["echo", "engine"],
            heartbeat_file=hb,
            hung_threshold_seconds=10,
            restart_delay_seconds=0,
            now_fn=lambda: 5000.0,
            sleep_fn=lambda s: None,
            log_fn=logs.append,
        )
        process = FakeProcess()
        supervisor.process = process
        hb.write_text("1000.0", encoding="utf-8")  # heartbeat très vieux

        assert supervisor.step()
        assert process.killed
        assert any("bloqué" in msg for msg in logs)

    def test_too_many_restarts_stops(self, tmp_path):
        hb = tmp_path / "hb"
        supervisor = Supervisor(
            command=["echo"],
            heartbeat_file=hb,
            max_restarts_per_hour=2,
            now_fn=lambda: 1000.0,
            sleep_fn=lambda s: None,
        )
        supervisor.restarts = [999.0, 999.5]
        assert supervisor._too_many_restarts()
