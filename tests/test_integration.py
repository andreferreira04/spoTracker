"""Integration tests against the real Windows APIs.

Live test with the real Spotify app (play a song first):
    SPOTRACKER_LIVE=1 python -m pytest tests/test_integration.py -k live -s
"""
import os
import sys
import time

import pytest

import platform_utils as pu
from platform_utils import NowPlaying

windows_only = pytest.mark.skipif(sys.platform != "win32", reason="Windows only")


# ── Real Spotify (opt-in) ─────────────────────────────────────────────────────
@pytest.mark.skipif(os.environ.get("SPOTRACKER_LIVE") != "1", reason="set SPOTRACKER_LIVE=1 and play a song on Spotify")
def test_live_spotify_is_detected():
    state = pu.get_now_playing()
    print("\nSpotify reports:", state)
    assert state is not None, "Spotify not detected (is it open?)"
    assert state.playing and state.artist and state.title, "Spotify detected but not playing a song"


def test_get_now_playing_does_not_crash_on_this_machine():
    state = pu.get_now_playing()
    assert state is None or isinstance(state, NowPlaying)


# ── Windows ───────────────────────────────────────────────────────────────────
@windows_only
def test_windows_enumerates_real_windows():
    import tkinter as tk
    title = f"SpoTracker Test Artist - Song {os.getpid()}"
    root = tk.Tk()
    root.title(title)
    root.update()
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            windows = pu.list_windows()
            if any(t == title for t, _ in windows):
                break
            root.update()
            time.sleep(0.1)
        exe = dict(windows).get(title)
        assert exe is not None, "test window not found"
        assert os.path.samefile(exe, sys.executable) or os.path.basename(exe).lower().startswith("python")
        assert pu.find_window_title(os.path.basename(exe), [(title, exe)]) == title
        assert pu.parse_window_title(title) == NowPlaying("SpoTracker Test Artist", f"Song {os.getpid()}", True)
    finally:
        root.destroy()


@windows_only
def test_windows_documents_folder_is_real():
    assert pu.get_documents_folder().is_dir()
