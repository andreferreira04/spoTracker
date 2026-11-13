"""Turning tracking on/off from the tray."""
import importlib.util
from types import SimpleNamespace

import pytest

from conftest import ROOT
from platform_utils import NowPlaying


@pytest.fixture
def app(tmp_path, monkeypatch):
    """music-register.py loaded as a module, saving into a list instead of the CSV."""
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
    icon = SimpleNamespace(title="", update_menu=lambda: None)

    app.toggle_tracking(icon)
    assert not app.is_tracking_enabled()
    assert "paused" in icon.title
    app.tracking_tick(30)
    assert [r[:3] for r in app.saved] == [("Artist", "Song 1", 30)]

    # While off, songs are ignored
    play(monkeypatch, app, "Artist", "Song 2")
    app.tracking_tick(40)
    app.tracking_tick(200)
    assert len(app.saved) == 1

    # Back on: records again from the next song
    app.toggle_tracking(icon)
    assert app.is_tracking_enabled() and icon.title == app.APP_NAME
    app.tracking_tick(300)
    play(monkeypatch, app, "Artist", "Song 3")
    app.tracking_tick(400)
    assert [r[1] for r in app.saved] == ["Song 1", "Song 2"]
    assert app.saved[1][2] == 100
