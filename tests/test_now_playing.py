"""How the Spotify window title becomes a NowPlaying (no Spotify needed)."""
import pytest

import platform_utils as pu
from platform_utils import NowPlaying, PAUSED


# ── Windows window titles ─────────────────────────────────────────────────────
@pytest.mark.parametrize("title, expected", [
    ("Drake - Mob Ties", NowPlaying("Drake", "Mob Ties", True)),
    # Only the first " - " separates the artist: the rest belongs to the song
    ("NF - The Search - Live", NowPlaying("NF", "The Search - Live", True)),
    ("Artist A, Artist B - Song", NowPlaying("Artist A, Artist B", "Song", True)),
    ("Spotify", PAUSED),
    ("Spotify Premium", PAUSED),
    ("Advertisement", PAUSED),
    ("", PAUSED),
    (None, PAUSED),
])
def test_parse_window_title(title, expected):
    assert pu.parse_window_title(title) == expected


def test_find_window_title_matches_exe_name_case_insensitively():
    windows = [
        ("Some editor", r"C:\Program Files\Editor\editor.exe"),
        ("", r"C:\Users\x\AppData\Roaming\Spotify\Spotify.exe"),   # untitled helper window
        ("Drake - Mob Ties", r"C:\Users\x\AppData\Roaming\Spotify\SPOTIFY.EXE"),
    ]
    assert pu.find_window_title("Spotify.exe", windows) == "Drake - Mob Ties"


def test_find_window_title_none_when_process_missing_or_inaccessible():
    assert pu.find_window_title("Spotify.exe", [("Drake - Mob Ties", None), ("x", "/usr/bin/x")]) is None
    assert pu.find_window_title("Spotify.exe", []) is None


def test_windows_now_playing(monkeypatch):
    monkeypatch.setattr(pu, "find_window_title", lambda exe: "Drake - Mob Ties")
    assert pu._now_playing_windows() == NowPlaying("Drake", "Mob Ties", True)
    monkeypatch.setattr(pu, "find_window_title", lambda exe: None)
    assert pu._now_playing_windows() is None


# ── Dispatch ──────────────────────────────────────────────────────────────────
def test_get_now_playing_uses_the_windows_backend(monkeypatch, as_platform):
    as_platform("windows")
    monkeypatch.setattr(pu, "_now_playing_windows", lambda: "windows")
    assert pu.get_now_playing() == "windows"


def test_get_now_playing_other_platforms(as_platform):
    as_platform("other")
    assert pu.get_now_playing() is None
