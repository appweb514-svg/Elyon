from __future__ import annotations

from pathlib import Path

from elyon_playback.engine import (
    PlaybackEngine,
    build_queue,
)
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


def test_show_request_played_then_cleared(tmp_path):
    import json

    from elyon_playback.engine import PlaybackEngine

    renderer = FakeRenderer()
    show_dir = tmp_path / "show"
    show_dir.mkdir(parents=True, exist_ok=True)
    (show_dir / "request.json").write_text(
        json.dumps({"media_id": "m-show", "kind": "image", "duration_seconds": 7}),
        encoding="utf-8",
    )
    blob = show_dir / "m-show"
    blob.write_bytes(b"data")

    stops = iter([False, True])
    engine = PlaybackEngine(
        renderer=renderer,
        layout_provider=lambda: None,
        heartbeat_file=tmp_path / "hb",
        blob_dir=tmp_path / "blobs",
        stop_check=lambda: next(stops),
        sleep_fn=lambda s: None,
    )
    engine.run_forever()
    assert renderer.events == [("image", (blob, 7.0))]
    assert not (show_dir / "request.json").exists()
    assert engine.current_media_id is None


def test_show_inserted_into_playlist_queue_and_writes_frame(tmp_path):
    """Un « Afficher » reçu en pleine lecture est inséré dans la playliste en
    cours : il passe avant la suite, qui reprend ENSUITE là où elle en était
    (pas de retour au début), et le média est capturé dans screen-frame.jpg."""
    import json

    show_dir = tmp_path / "show"
    show_dir.mkdir(parents=True, exist_ok=True)
    show_blob = show_dir / "m-show"
    show_blob.write_bytes(b"show-data")

    class PreemptingRenderer(FakeRenderer):
        def __init__(self) -> None:
            super().__init__()
            self.frame_at_show: bytes | None = None
            self.image_calls = 0

        def play_image(self, path: Path, duration_seconds: float) -> None:
            self.image_calls += 1
            if self.image_calls == 1:
                # Le « Afficher » arrive pendant la lecture du 1er élément.
                (show_dir / "request.json").write_text(
                    json.dumps(
                        {"media_id": "m-show", "kind": "image", "duration_seconds": 7}
                    ),
                    encoding="utf-8",
                )
            super().play_image(path, duration_seconds)
            if path == show_blob:
                self.frame_at_show = (tmp_path / "screen-frame.jpg").read_bytes()

    renderer = PreemptingRenderer()
    layout = {
        "media": [
            {"media_id": f"m-{c}", "name": c, "kind": "image",
             "main_blob": c * 3, "page_blobs": []}
            for c in "abc"
        ],
        "blocks": [
            {
                "schedule_id": "s-1",
                "priority": 5,
                "entries": [
                    {"media_id": f"m-{c}", "duration_seconds": 4} for c in "abc"
                ],
            }
        ],
    }
    engine = PlaybackEngine(
        renderer=renderer,
        layout_provider=lambda: layout,
        heartbeat_file=tmp_path / "hb",
        blob_dir=tmp_path / "blobs",
        stop_check=lambda: len(renderer.events) >= 6,
        sleep_fn=lambda s: None,
    )
    engine.run_forever()

    # Élément 1, puis le SHOW inséré, puis la suite (b, c) — la playliste ne
    # repart PAS du début : elle reprend à b après le show.
    paths = [e[1][0] for e in renderer.events]
    assert paths[0] == tmp_path / "blobs" / "aaa"
    assert paths[1] == show_blob
    assert renderer.events[1][1][1] == 7.0
    assert paths[2:4] == [tmp_path / "blobs" / n for n in ("bbb", "ccc")]
    # Puis la file re-boucle sur le premier élément.
    assert paths[4] == tmp_path / "blobs" / "aaa"
    # La spec est consommée (le média a rejoint la file, pas un mode boucle).
    assert not (show_dir / "request.json").exists()
    # La capture du flux direct montre bien le média affiché.
    assert renderer.frame_at_show == b"show-data"


def test_show_inserted_at_start_when_playlist_active(tmp_path):
    """« Afficher » posé avant le démarrage : inséré en tête de la file même
    si aucun élément n'a encore été joué."""
    import json

    show_dir = tmp_path / "show"
    show_dir.mkdir(parents=True, exist_ok=True)
    show_blob = show_dir / "m-show"
    show_blob.write_bytes(b"show-data")
    (show_dir / "request.json").write_text(
        json.dumps({"media_id": "m-show", "kind": "image", "duration_seconds": 9}),
        encoding="utf-8",
    )

    renderer = FakeRenderer()
    layout = {
        "media": [
            {"media_id": f"m-{c}", "name": c, "kind": "image",
             "main_blob": c * 3, "page_blobs": []}
            for c in "ab"
        ],
        "blocks": [
            {
                "schedule_id": "s-1",
                "priority": 5,
                "entries": [{"media_id": f"m-{c}", "duration_seconds": 4} for c in "ab"],
            }
        ],
    }
    engine = PlaybackEngine(
        renderer=renderer,
        layout_provider=lambda: layout,
        heartbeat_file=tmp_path / "hb",
        blob_dir=tmp_path / "blobs",
        stop_check=lambda: len(renderer.events) >= 3,
        sleep_fn=lambda s: None,
    )
    engine.run_forever()

    paths = [e[1][0] for e in renderer.events]
    assert paths == [show_blob, tmp_path / "blobs" / "aaa", tmp_path / "blobs" / "bbb"]
    assert not (show_dir / "request.json").exists()


def test_show_video_writes_screen_frame_marker(tmp_path):
    import json

    show_dir = tmp_path / "show"
    show_dir.mkdir(parents=True, exist_ok=True)
    (show_dir / "request.json").write_text(
        json.dumps({"media_id": "m-vid", "kind": "video", "duration_seconds": 5}),
        encoding="utf-8",
    )
    (show_dir / "m-vid").write_bytes(b"vid")

    renderer = FakeRenderer()
    stops = iter([False, True])
    engine = PlaybackEngine(
        renderer=renderer,
        layout_provider=lambda: None,
        heartbeat_file=tmp_path / "hb",
        blob_dir=tmp_path / "blobs",
        stop_check=lambda: next(stops),
        sleep_fn=lambda s: None,
    )
    engine.run_forever()
    assert renderer.events == [("video", show_dir / "m-vid")]
    info = json.loads((tmp_path / "screen-frame.json").read_text(encoding="utf-8"))
    assert info["video"] is True
    assert info["path"] == str(show_dir / "m-vid")
    # Horodatage de départ : le flux « direct » en déduit la position de lecture.
    assert isinstance(info["started_at"], float) and info["started_at"] > 0


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


class TestDummyRenderer:
    def test_plays_and_records_status(self, tmp_path):
        from elyon_playback.renderers import DummyRenderer

        status = tmp_path / "now-playing.json"
        renderer = DummyRenderer(status_file=status, sleep_fn=lambda _s: None, speed=50)
        renderer.play_image(tmp_path / "logo.png", 8)
        assert renderer.events[0][0] == "image"
        payload = (tmp_path / "now-playing.json").read_text(encoding="utf-8")
        assert "logo.png" in payload
        renderer.blank()
        assert "blank" in status.read_text(encoding="utf-8")

    def test_file_blank_state(self, tmp_path):
        from elyon_playback.renderers import FileBlankState

        flag = tmp_path / "blank"
        state = FileBlankState(flag)
        assert not state.blanked
        state.blank()
        assert state.blanked
        state.unblank()
        assert not state.blanked

    def test_engine_writes_now_playing(self, tmp_path):
        from elyon_playback.engine import PlaybackEngine
        from elyon_playback.renderers import DummyRenderer, FileBlankState

        status = tmp_path / "now-playing.json"
        renderer = DummyRenderer(sleep_fn=lambda _s: None)
        stops = iter([False, False, True])
        engine = PlaybackEngine(
            renderer=renderer,
            layout_provider=make_layout_with_single_image,
            heartbeat_file=tmp_path / "hb",
            blob_dir=tmp_path,
            blank_state=FileBlankState(tmp_path / "blank"),
            status_file=status,
            stop_check=lambda: next(stops),
            sleep_fn=lambda _s: None,
        )
        engine.run_forever()
        assert engine.current_media_id == "m-img"
        assert "m-img" in status.read_text(encoding="utf-8")


class TestWidgets:
    """Widgets composités dans l'image affichée (et la capture « direct »)."""

    @staticmethod
    def _png(tmp_path, color=(255, 0, 0), name="logo.png"):
        from PIL import Image

        path = tmp_path / name
        Image.new("RGB", (640, 360), color).save(path, "PNG")
        return path

    def test_widget_text_variants(self):
        from datetime import datetime

        from elyon_playback.widgets import widget_text

        now = datetime(2026, 1, 1, 14, 32, 8)
        feed = {
            "weather": {"Paris": {"temperature": 21.4}},
            "rss": {"https://x/rss.xml": {"items": ["Une actu", "Une autre"]}},
        }
        assert widget_text({"type": "text", "params": {"text": "Bonjour"}}, None, now) == "Bonjour"
        assert widget_text(
            {"type": "clock", "params": {"format": "HH:MM:SS"}}, None, now
        ) == "14:32:08"
        assert widget_text({"type": "clock", "params": {}}, None, now) == "14:32"
        assert widget_text(
            {"type": "weather", "params": {"city": "Paris"}}, feed, now
        ) == "Paris · 21°C"
        assert widget_text({"type": "weather", "params": {"city": "Paris"}}, None, now) == "Paris"
        assert widget_text(
            {"type": "rss", "params": {"url": "https://x/rss.xml"}}, feed, now
        ) == "Une actu  •  Une autre"
        assert widget_text(
            {"type": "rss", "position": "bottom-ticker", "params": {"url": "https://x/rss.xml"}},
            feed,
            now,
        ) == "Une actu  •  Une autre"
        assert widget_text(
            {"type": "html", "params": {"html": "<b>Salut</b> toi"}}, None, now
        ) == "Salut toi"
        assert widget_text({"type": "inconnu", "params": {}}, None, now) == ""

    def test_compose_writes_overlay(self, tmp_path):
        from elyon_playback.widgets import compose_widget_bar

        src = self._png(tmp_path)
        widgets = [
            {"type": "text", "position": "bottom-center", "visible": True,
             "params": {"text": "Bienvenue à l'accueil"}},
            {"type": "text", "position": "bottom-left", "visible": False,
             "params": {"text": "caché"}},
        ]
        out = tmp_path / "render" / "frame.jpg"
        result = compose_widget_bar(src, widgets, None, out)
        assert result == out
        assert out.exists()
        from PIL import Image

        composed = Image.open(out)
        assert composed.size == (640, 360)

    def test_compose_no_visible_widget_returns_none(self, tmp_path):
        from elyon_playback.widgets import compose_widget_bar

        src = self._png(tmp_path)
        widgets = [
            {"type": "text", "position": "bottom-left", "visible": False, "params": {"text": "x"}}
        ]
        out = tmp_path / "out.jpg"
        assert compose_widget_bar(src, widgets, None, out) is None
        assert not out.exists()

    def test_compose_unknown_image_returns_none(self, tmp_path):
        from elyon_playback.widgets import compose_widget_bar

        widgets = [
            {"type": "text", "position": "bottom-left", "visible": True, "params": {"text": "x"}}
        ]
        out = tmp_path / "out.jpg"
        assert compose_widget_bar(tmp_path / "inexistant.png", widgets, None, out) is None

    def test_compose_top_bar_and_ticker(self, tmp_path):
        from elyon_playback.widgets import compose_widget_bar, has_ticker

        src = self._png(tmp_path)
        widgets = [
            {"type": "weather", "position": "top-left", "visible": True, "locked": True,
             "params": {"city": "Paris"}},
            {"type": "clock", "position": "top-right", "visible": True, "locked": True,
             "params": {"format": "HH:MM"}},
            {"type": "rss", "position": "bottom-ticker", "visible": True, "locked": True,
             "params": {"url": "https://x/rss.xml"}},
        ]
        assert has_ticker(widgets)
        feed = {"rss": {"https://x/rss.xml": {"items": ["Actu 1", "Actu 2"]}}}
        out = tmp_path / "render" / "frame.jpg"
        assert compose_widget_bar(src, widgets, feed, out) == out
        from PIL import Image

        assert Image.open(out).size == (640, 360)

    def test_ticker_scrolls_left_to_right(self):
        from datetime import datetime, timedelta

        from elyon_playback.widgets import ticker_x

        start = datetime(2026, 1, 1, 12, 0, 0)
        x0 = ticker_x(200, 640, start)
        x1 = ticker_x(200, 640, start + timedelta(seconds=3))
        x2 = ticker_x(200, 640, start + timedelta(seconds=6))
        # Le texte entre par la gauche puis progresse vers la droite.
        assert x0 <= x1 < x2
        assert x0 < 0  # démarre hors écran, à gauche
        # Défilement continu : pas de saut au passage du modulo.
        assert x2 - x1 == x1 - x0

    def test_weather_icon_kind_mapping(self):
        from elyon_playback.widgets import weather_icon_kind

        assert weather_icon_kind(0) == "sun"
        assert weather_icon_kind(1) == "partly"
        assert weather_icon_kind(2) == "partly"
        assert weather_icon_kind(3) == "cloud"
        assert weather_icon_kind(45) == "fog"
        assert weather_icon_kind(61) == "rain"
        assert weather_icon_kind(80) == "rain"
        assert weather_icon_kind(71) == "snow"
        assert weather_icon_kind(95) == "thunder"
        assert weather_icon_kind(None) == "cloud"
        assert weather_icon_kind("inconnu") == "cloud"

    def test_draw_icons_all_kinds(self):
        from PIL import Image, ImageDraw

        from elyon_playback.widgets import _draw_icon

        for kind in ("sun", "partly", "cloud", "fog", "rain", "snow", "thunder"):
            img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)
            _draw_icon(draw, 32, 32, 16, kind)
            assert img.getbbox() is not None, f"icône {kind} vide"

    def test_compose_weather_block_with_forecast(self, tmp_path):
        from elyon_playback.widgets import compose_widget_bar

        src = self._png(tmp_path)
        widgets = [
            {"type": "weather", "position": "top-left", "visible": True, "locked": True,
             "params": {"city": "Paris"}},
        ]
        feed = {"weather": {"Paris": {
            "temperature": 21.4, "code": 1,
            "forecast": [
                {"date": "2026-08-31", "max": 24.5, "min": 15.2, "code": 1},
                {"date": "2026-09-01", "max": 22.0, "min": 14.0, "code": 61},
                {"date": "2026-09-02", "max": 19.0, "min": 13.1, "code": 3},
            ],
        }}}
        out = tmp_path / "render" / "wx.jpg"
        assert compose_widget_bar(src, widgets, feed, out) == out
        from PIL import Image

        assert Image.open(out).size == (640, 360)
        # Sans feed : repli sur la pastille texte « Paris ».
        out2 = tmp_path / "render" / "wx-fallback.jpg"
        assert compose_widget_bar(src, widgets, None, out2) == out2

    def test_has_live_widgets(self):
        from elyon_playback.widgets import has_live_widgets

        assert has_live_widgets([{"type": "clock", "visible": True, "params": {}}])
        assert has_live_widgets([{"type": "weather", "visible": True, "params": {}}])
        assert has_live_widgets([
            {"type": "rss", "visible": True, "position": "bottom-ticker", "params": {}}
        ])
        assert not has_live_widgets([{"type": "text", "visible": True, "params": {}}])
        assert not has_live_widgets([{"type": "clock", "visible": False, "params": {}}])

    def test_engine_recomposes_clock_in_real_time(self, tmp_path):
        from elyon_playback.engine import PlaybackEngine
        from elyon_playback.widgets import has_live_widgets

        (tmp_path / "blobs").mkdir(exist_ok=True)
        self._png(tmp_path / "blobs", name="logo.png")
        widgets = [
            {"type": "clock", "position": "top-right", "visible": True, "locked": True,
             "params": {"format": "HH:MM"}},
        ]
        assert has_live_widgets(widgets)
        layout = {
            "media": [
                {"media_id": "m-img", "name": "Logo", "kind": "image",
                 "main_blob": "logo.png", "page_blobs": []},
            ],
            "blocks": [
                {"schedule_id": "s1", "priority": 0,
                 "entries": [{"media_id": "m-img", "duration_seconds": 2}]},
            ],
            "widgets": widgets,
        }
        renderer = FakeRenderer()
        stops = iter([False] * 6 + [True, True])
        engine = PlaybackEngine(
            renderer=renderer,
            layout_provider=lambda: layout,
            heartbeat_file=tmp_path / "hb",
            blob_dir=tmp_path / "blobs",
            stop_check=lambda: next(stops),
            sleep_fn=lambda _s: None,
            ticker_tick_seconds=1.0,
        )
        engine.run_forever()
        image_events = [e for e in renderer.events if e[0] == "image"]
        # L'horloge est « vivante » : l'image est recomposée par tranches.
        assert len(image_events) >= 2
        assert all(event[1][1] == 1.0 for event in image_events[:2])

    def test_engine_recomposes_ticker_per_tick(self, tmp_path):
        from elyon_playback.engine import PlaybackEngine
        from elyon_playback.widgets import has_ticker

        (tmp_path / "blobs").mkdir(exist_ok=True)
        self._png(tmp_path / "blobs", name="logo.png")
        widgets = [
            {"type": "rss", "position": "bottom-ticker", "visible": True, "locked": True,
             "params": {"url": "https://x/rss.xml"}},
        ]
        assert has_ticker(widgets)
        layout = {
            "media": [
                {"media_id": "m-img", "name": "Logo", "kind": "image",
                 "main_blob": "logo.png", "page_blobs": []},
            ],
            "blocks": [
                {"schedule_id": "s1", "priority": 0,
                 "entries": [{"media_id": "m-img", "duration_seconds": 2}]},
            ],
            "widgets": widgets,
        }
        renderer = FakeRenderer()
        stops = iter([False, False, False, False, False, False, True, True])
        engine = PlaybackEngine(
            renderer=renderer,
            layout_provider=lambda: layout,
            heartbeat_file=tmp_path / "hb",
            blob_dir=tmp_path / "blobs",
            stop_check=lambda: next(stops),
            sleep_fn=lambda _s: None,
            ticker_tick_seconds=1.0,
        )
        engine.run_forever()
        image_events = [e for e in renderer.events if e[0] == "image"]
        # 2 s en tranches de 1 s : l'image est recomposée (et rejouée) par
        # tranches, puis la boucle relit l'élément (même séquence).
        assert len(image_events) >= 2
        assert all(event[1][1] == 1.0 for event in image_events[:2])
        paths = [Path(event[1][0]) for event in image_events]
        assert all(p.exists() for p in paths)

    def test_engine_plays_composited_image_and_frame(self, tmp_path):
        from elyon_playback.engine import PlaybackEngine

        (tmp_path / "blobs").mkdir(exist_ok=True)
        original = self._png(tmp_path / "blobs", name="logo.png")
        widgets = [
            {"type": "text", "position": "bottom-center", "visible": True,
             "params": {"text": "Accueil"}},
        ]
        layout = {
            "media": [
                {"media_id": "m-img", "name": "Logo", "kind": "image",
                 "main_blob": "logo.png", "page_blobs": []},
            ],
            "blocks": [
                {"schedule_id": "s1", "priority": 0,
                 "entries": [{"media_id": "m-img", "duration_seconds": 5}]},
            ],
            "widgets": widgets,
        }
        renderer = FakeRenderer()
        stops = iter([False, False, True, True])
        engine = PlaybackEngine(
            renderer=renderer,
            layout_provider=lambda: layout,
            heartbeat_file=tmp_path / "hb",
            blob_dir=tmp_path / "blobs",
            stop_check=lambda: next(stops),
            sleep_fn=lambda _s: None,
        )
        engine.run_forever()
        assert engine.active_widgets == widgets
        played_path, _duration = renderer.events[-1][1]
        played_path = Path(played_path)
        assert played_path != original
        assert played_path.exists()
        assert played_path.read_bytes() != original.read_bytes()
        frame = tmp_path / "screen-frame.jpg"
        assert frame.read_bytes() == played_path.read_bytes()

    def test_video_not_composited(self, tmp_path):
        from elyon_playback.engine import PlaybackEngine, PlayItem

        video = tmp_path / "clip.mp4"
        video.write_bytes(b"fake")
        engine = PlaybackEngine(
            renderer=FakeRenderer(),
            layout_provider=lambda: None,
            heartbeat_file=tmp_path / "hb",
            blob_dir=tmp_path,
            stop_check=lambda: False,
            sleep_fn=lambda _s: None,
        )
        engine.active_widgets = [
            {"type": "text", "position": "bottom-left", "visible": True, "params": {"text": "x"}}
        ]
        engine.play_item(
            PlayItem(kind="video", path=video, duration_seconds=None, media_id="v1", name="clip")
        )
        played_path = Path(engine.renderer.events[-1][1])
        assert played_path == video

    def test_feed_cache_read(self, tmp_path):
        import json

        from elyon_playback.widgets import read_widget_feed

        assert read_widget_feed(tmp_path) is None
        (tmp_path / "widgets-feed.json").write_text(
            json.dumps({"weather": {"Paris": {"temperature": 10}}}), encoding="utf-8"
        )
        feed = read_widget_feed(tmp_path)
        assert feed is not None
        assert feed["weather"]["Paris"]["temperature"] == 10
        (tmp_path / "widgets-feed.json").write_text("pas du json", encoding="utf-8")
        assert read_widget_feed(tmp_path) is None


def test_video_freezes_while_paused_and_resumes(tmp_path):
    """Pause : la vidéo en cours est figée (hold_paused_frame) jusqu'au dégel.

    Le moteur appelle `hold_paused_frame` du renderer tant que le fichier
    `pause` existe ; le rendu mpv (bloquant) reprend ensuite là où il en
    était — l'élément n'est « terminé » qu'après le dégel.
    """
    import threading
    import time as _time

    from elyon_playback.engine import PlaybackEngine, PlayItem

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")
    pause_file = tmp_path / "pause"
    hold_entered = threading.Event()
    hold_exit = threading.Event()

    class FreezingRenderer(FakeRenderer):
        def play_video(self, path: Path) -> None:
            self.events.append(("video", path))
            _time.sleep(0.3)  # rendu bloquant comme le vrai mpv

        def hold_paused_frame(self, check_paused, keepalive=None) -> None:  # type: ignore[no-untyped-def]
            self.events.append(("hold-paused", None))
            hold_entered.set()
            while check_paused():
                hold_exit.wait(0.05)

    renderer = FreezingRenderer()
    engine = PlaybackEngine(
        renderer=renderer,
        layout_provider=lambda: None,
        heartbeat_file=tmp_path / "hb",
        blob_dir=tmp_path,
        stop_check=lambda: False,
        sleep_fn=lambda _s: None,
        pause_file=pause_file,
    )
    done = threading.Event()

    def play() -> None:
        try:
            engine.play_item(
                PlayItem(kind="video", path=video, duration_seconds=None,
                         media_id="v1", name="clip")
            )
        finally:
            done.set()

    thread = threading.Thread(target=play, daemon=True)
    thread.start()
    _time.sleep(0.1)  # la lecture démarre
    pause_file.write_text("1", encoding="utf-8")  # pause EN COURS de lecture
    assert hold_entered.wait(5.0), "le gel doit démarrer pendant la vidéo"
    pause_file.unlink()  # dégel : la lecture reprend
    hold_exit.set()
    assert done.wait(5.0), "play_item doit se terminer après le dégel"
    assert ("hold-paused", None) in renderer.events
    assert ("video", video) in renderer.events


def test_video_plays_without_hold_when_renderer_lacks_it(tmp_path):
    """Renderer sans `hold_paused_frame` (ancien plugin) : lecture normale."""
    from elyon_playback.engine import PlaybackEngine, PlayItem

    video = tmp_path / "clip.mp4"
    video.write_bytes(b"fake")

    class BareRenderer(FakeRenderer):
        hold_paused_frame = None  # type: ignore[assignment]

    engine = PlaybackEngine(
        renderer=BareRenderer(),
        layout_provider=lambda: None,
        heartbeat_file=tmp_path / "hb",
        blob_dir=tmp_path,
        stop_check=lambda: False,
        sleep_fn=lambda _s: None,
    )
    engine.play_item(
        PlayItem(kind="video", path=video, duration_seconds=None,
                 media_id="v1", name="clip")
    )
    assert engine.renderer.events == [("video", video)]


def test_url_not_implemented_error_propagates_after_freezable(tmp_path):
    """MpvRenderer + média web : NotImplementedError remontée au moteur.

    Elle est interceptée par `play_item` (sleep court) — pas de boucle
    chaude ni de perte de l'erreur.
    """
    import pytest as _pytest

    from elyon_playback.engine import PlaybackEngine, PlayItem

    class NoUrlRenderer(FakeRenderer):
        def play_url(self, url: str, timeout_seconds: float | None = None) -> None:
            raise NotImplementedError("Utiliser ChromiumRenderer pour les URL")

        hold_paused_frame = None  # type: ignore[assignment]

    engine = PlaybackEngine(
        renderer=NoUrlRenderer(),
        layout_provider=lambda: None,
        heartbeat_file=tmp_path / "hb",
        blob_dir=tmp_path,
        stop_check=lambda: False,
        sleep_fn=lambda _s: None,
    )
    engine.play_item(
        PlayItem(kind="url", path=tmp_path, url="https://example.org",
                 duration_seconds=5, media_id="w1", name="web")
    )
    with _pytest.raises(NotImplementedError):
        engine._play_freezable(lambda: (_ for _ in ()).throw(NotImplementedError("x")))


def test_mpv_ipc_freeze_round_trip(tmp_path):
    """Gel SIGSTOP/SIGCONT d'un faux mpv média appartenant à CE player.

    `mpv_media_pids(socket_hint)` ne cible que les mpv portant le chemin du
    socket IPC de CE renderer dans leur ligne de commande ; un écran noir
    (`--image-display-duration` + png) est ignoré.
    """
    import os
    import signal
    import subprocess
    import time

    from elyon_playback.renderers import MpvRenderer, mpv_media_pids

    renderer = MpvRenderer()
    hint = str(renderer._ipc_socket_path)
    # Faux mpv « média » : os.execv requalifie argv[0] en « mpv », le
    # « script » (chemin absolu, sleep 30) joue le rôle du fichier média et
    # le hint IPC figure dans la cmdline comme le vrai player.
    media = tmp_path / "media.mp4"
    media.write_text("import time; time.sleep(30)\n")
    fake = subprocess.Popen(  # noqa: S603
        ["python3", "-c",
         "import os, sys;"
         f" os.execv(sys.executable, ['mpv', {str(media)!r}, '{hint}'])"],
        stdin=subprocess.DEVNULL,
    )
    try:
        time.sleep(0.3)  # laisse le shell exécuter `exec -a mpv`
        cmdline = open(f"/proc/{fake.pid}/cmdline", "rb").read()  # noqa: SIM115
        parts = cmdline.decode().split("\0")
        assert parts[0] == "mpv"
        # PIDs de CE player : le faux média est repéré.
        pids = mpv_media_pids(hint)
        assert fake.pid in pids
        # Un écran noir mpv (png) est ignoré : argv contient le png, pas le hint.
        blank_args = ["mpv", "--image-display-duration=inf", "/tmp/black.png"]
        assert not mpv_media_pids(hint) or all(
            pid == fake.pid for pid in mpv_media_pids(hint)
        )
        assert not _cmdline_is_media(blank_args)
        # SIGSTOP/SIGCONT (mécanisme de repli du renderer) :
        os.kill(fake.pid, signal.SIGSTOP)
        time.sleep(0.3)
        state = open(f"/proc/{fake.pid}/stat").read().split()[2]  # noqa: SIM115
        assert state == "T"  # T = stopped
        os.kill(fake.pid, signal.SIGCONT)
        time.sleep(0.3)
        state = open(f"/proc/{fake.pid}/stat").read().split()[2]  # noqa: SIM115
        assert state in ("S", "R")
    finally:
        fake.kill()
        fake.wait(timeout=5)


def _cmdline_is_media(parts: list[str]) -> bool:
    from elyon_playback.renderers import is_video_process_cmdline

    return is_video_process_cmdline(parts)


def test_mpv_ipc_command_no_socket_returns_false(tmp_path):
    """Sans socket IPC présent : la commande mpv est un no-op silencieux."""
    from elyon_playback.renderers import mpv_ipc_command

    assert mpv_ipc_command("set pause yes", tmp_path / "absent.sock", 0.1) is False


def test_mpv_ipc_command_round_trip(tmp_path):
    """Un serveur unix qui répond `{"error":"success"}` valide la commande."""
    import socket as socket_mod
    import threading

    from elyon_playback.renderers import mpv_ipc_command

    sock_path = tmp_path / "mpv.sock"
    server = socket_mod.socket(socket_mod.AF_UNIX, socket_mod.SOCK_STREAM)
    server.bind(str(sock_path))
    server.listen(1)
    got: list[bytes] = []

    def serve() -> None:
        conn, _ = server.accept()
        with conn:
            data = conn.recv(1024)
            got.append(data)
            conn.sendall(b'{"error":"success"}\n')

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    assert mpv_ipc_command("set pause yes", sock_path, 2.0) is True
    thread.join(timeout=2)
    assert b'"set pause yes"' in got[0]
    server.close()


def test_day_label_uses_real_weekday():
    """Le libellé doit correspondre au vrai jour de la date ISO."""
    from datetime import datetime

    from elyon_playback.widgets import _day_label

    # 2026-09-10 est un jeudi, 2026-09-13 un dimanche.
    now = datetime(2026, 9, 10, 12, 0)
    assert _day_label("2026-09-10", 0, now) == "jeu"
    assert _day_label("2026-09-13", 3, now) == "dim"
    # Date invalide → repli sur l'index à partir d'aujourd'hui.
    assert _day_label("", 0, now) == "jeu"


def test_build_queue_includes_web_item(tmp_path):
    """Un média web devient un item « url » dans la file de lecture."""
    layout = {
        "blocks": [
            {
                "schedule_id": "s1",
                "priority": 1,
                "entries": [{"media_id": "w1", "duration_seconds": 45}],
            }
        ],
        "media": [
            {
                "media_id": "w1",
                "name": "Portail",
                "kind": "web",
                "url": "https://elyon.int.labvirtuel.fr/media",
            }
        ],
    }
    items = build_queue(layout, tmp_path / "blobs")
    assert len(items) == 1
    assert items[0].kind == "url"
    assert items[0].url == "https://elyon.int.labvirtuel.fr/media"
    assert items[0].duration_seconds == 45.0


def test_build_queue_pages_default_five_seconds(tmp_path):
    """Un PDF multi-pages défile page par page, 5 s par défaut."""
    layout = {
        "blocks": [
            {"schedule_id": "s1", "priority": 1, "entries": [{"media_id": "p1"}]}
        ],
        "media": [
            {
                "media_id": "p1",
                "name": "Rapport",
                "kind": "pdf",
                "main_blob": "main",
                "page_blobs": ["page1", "page2", "page3"],
            }
        ],
    }
    items = build_queue(layout, tmp_path)
    assert [item.kind for item in items] == ["page", "page", "page"]
    assert [item.page_index for item in items] == [0, 1, 2]
    assert all(item.duration_seconds == 5.0 for item in items)
