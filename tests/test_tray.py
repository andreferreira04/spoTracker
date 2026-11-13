"""Turning tracking on/off from the tray."""
import importlib.util
from types import SimpleNamespace

import pytest

from conftest import ROOT
from platform_utils import NowPlaying


@pytest.fixture
def app(tmp_path, monkeypatch):
    """music-register.py loaded as a module, saving into a list instead of the CSV."""
    monkeypatch.setenv("SPOTRACKER_DATA_DIR", str(tmp_path))  # settings.json goes here
    spec = importlib.util.spec_from_file_location("music_register", ROOT / "music-register.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    saved = []
    module._tracker.save = lambda *record: saved.append(record)
    module.saved = saved
    return module


def play(monkeypatch, app, artist, title, playing=True):
    monkeypatch.setattr(app.pu, "get_now_playing", lambda: NowPlaying(artist, title, playing))


def test_turning_tracking_off_saves_the_current_song_and_stops_recording(app, monkeypatch):
    play(monkeypatch, app, "Artist", "Song 1")
    app.tracking_tick(0)
    icon = SimpleNamespace(title="", icon=None, update_menu=lambda: None)

    app.toggle_tracking(icon)
    assert not app.is_tracking_enabled()
    assert "Tracking paused" in icon.title
    assert icon.icon.getpixel((32, 32))[0] == icon.icon.getpixel((32, 32))[1]  # greyscale while off
    app.tracking_tick(30)
    assert [r[:3] for r in app.saved] == [("Artist", "Song 1", 30)]

    # While off, songs are ignored
    play(monkeypatch, app, "Artist", "Song 2")
    app.tracking_tick(40)
    app.tracking_tick(200)
    assert len(app.saved) == 1

    # Back on: records again from the next song
    app.toggle_tracking(icon)
    assert app.is_tracking_enabled()
    app.tracking_tick(300)
    play(monkeypatch, app, "Artist", "Song 3")
    app.tracking_tick(400)
    assert [r[1] for r in app.saved] == ["Song 1", "Song 2"]
    assert app.saved[1][2] == 100


# ── Tooltip ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("enabled, state, error, expected", [
    (True, NowPlaying("Artist", "Song", True), False, "Artist – Song"),
    (True, NowPlaying("", "Podcast", True), False, "Podcast"),
    (True, NowPlaying("Artist", "Song", False), False, "Spotify paused"),
    (True, None, False, "Spotify is not open"),
    (True, None, True, "Can't read Spotify"),
    (False, NowPlaying("Artist", "Song", True), False, "Tracking paused"),
])
def test_tray_status(app, enabled, state, error, expected):
    text = app.tray_status(enabled, state, error)
    assert text.startswith(app.APP_NAME + "\n") and expected in text


def test_tray_status_fits_the_windows_tooltip_limit(app):
    text = app.tray_status(True, NowPlaying("A" * 100, "B" * 100, True))
    assert len(text) == app.TOOLTIP_MAX and text.endswith("…")


def test_loop_updates_the_tooltip(app, monkeypatch):
    app._tray_icon = SimpleNamespace(title="")
    play(monkeypatch, app, "Artist", "Song")
    app.tracking_tick(0)
    assert app._tray_icon.title.endswith("Artist – Song")

    def broken():
        raise OSError("no window")
    monkeypatch.setattr(app.pu, "get_now_playing", broken)
    app.tracking_tick(1)
    assert "Can't read Spotify" in app._tray_icon.title


# ── Remembering the tracking state ────────────────────────────────────────────
def test_tracking_state_is_saved_and_only_restored_when_remembering(app):
    import settings
    assert app.initial_tracking_state() is True
    app.toggle_tracking()                       # off
    assert settings.load()["tracking_enabled"] is False
    assert app.initial_tracking_state() is True  # not remembering: starts on anyway
    settings.update(remember_tracking_state=True)
    assert app.initial_tracking_state() is False
    app.toggle_tracking()                       # back on
    assert app.initial_tracking_state() is True
