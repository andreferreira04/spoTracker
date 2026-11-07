"""Listening logic (pauses, ads, song changes, Spotify closing) and CSV writing."""
import os
import threading
from datetime import datetime

import pytest

import tracker
from platform_utils import FileLock, NowPlaying, PAUSED

SONG_A = NowPlaying("Drake", "Mob Ties", True)
SONG_B = NowPlaying("NF", "The Search", True)
DAY = datetime(2026, 9, 25, 21, 5, 30)


@pytest.fixture
def saved():
    return []


@pytest.fixture
def t(saved):
    return tracker.Tracker(lambda *record: saved.append(record))


def test_song_change_saves_previous_song(t, saved):
    assert t.update(SONG_A, 1000, DAY) is True
    assert t.update(SONG_A, 1030, DAY) is False
    assert t.update(SONG_B, 1100, DAY) is True
    assert saved == [("Drake", "Mob Ties", 100, "25-09-2026", "21:05:30")]
    assert (t.artist, t.music) == ("NF", "The Search")


def test_pauses_are_not_counted(t, saved):
    t.update(SONG_A, 1000, DAY)
    t.update(PAUSED, 1010, DAY)
    t.update(PAUSED, 1050, DAY)     # still the same pause
    t.update(SONG_A, 1060, DAY)     # resume
    t.update(PAUSED, 1070, DAY)
    t.update(SONG_A, 1075, DAY)
    t.update(SONG_B, 1080, DAY)
    assert saved[0][2] == 80 - 50 - 5


def test_closing_spotify_saves_current_song(t, saved):
    t.update(SONG_A, 1000, DAY)
    t.update(None, 1042, DAY)
    assert saved == [("Drake", "Mob Ties", 42, "25-09-2026", "21:05:30")]
    t.update(None, 1043, DAY)       # stays closed: nothing more
    assert len(saved) == 1


def test_closing_spotify_while_paused_excludes_ongoing_pause(t, saved):
    t.update(SONG_A, 1000, DAY)
    t.update(PAUSED, 1020, DAY)
    t.update(None, 1500, DAY)
    assert saved[0][2] == 20


def test_same_song_after_reopening_starts_fresh(t, saved):
    t.update(SONG_A, 1000, DAY)
    t.update(None, 1010, DAY)
    assert t.update(SONG_A, 2000, DAY) is True
    t.update(SONG_B, 2005, DAY)
    assert [s[2] for s in saved] == [10, 5]


def test_zero_seconds_not_saved_on_close(t, saved):
    t.update(SONG_A, 1000, DAY)
    t.update(None, 1000.5, DAY)
    assert saved == []


def test_nothing_saved_before_any_song(t, saved):
    t.update(PAUSED, 1000, DAY)
    t.update(None, 1010, DAY)
    t.update(PAUSED, 1020, DAY)
    t.update(SONG_A, 1030, DAY)
    assert saved == []


def test_ad_between_songs_counts_as_pause(t, saved):
    t.update(SONG_A, 1000, DAY)
    t.update(PAUSED, 1100, DAY)     # ad
    t.update(SONG_B, 1130, DAY)
    assert saved[0][2] == 100


def test_stop_saves_current_song(t, saved):
    t.update(SONG_A, 1000, DAY)
    t.stop(1030)
    assert saved[0][2] == 30
    t.stop(1040)
    assert len(saved) == 1


def test_date_defaults_to_today(t):
    t.update(SONG_A, 1000)
    assert t.date == datetime.today().strftime("%d-%m-%Y")


# ── CSV ───────────────────────────────────────────────────────────────────────
def read(path):
    return path.read_bytes().decode("utf-8").splitlines()


@pytest.fixture
def csv(tmp_path):
    return tmp_path / "music-list.csv"


@pytest.fixture
def lock(tmp_path):
    return FileLock(tmp_path / "music-list.lock")


@pytest.mark.parametrize("content, expected", [
    (b"", (0, b"")),
    (b"only;line", (0, b"only;line")),
    (b"a\nb\n", (2, b"b\n")),
    (b"a\r\nb\r\n", (3, b"b\r\n")),
])
def test_get_last_record(tmp_path, content, expected):
    p = tmp_path / "f"
    p.write_bytes(content)
    with open(p, "rb") as f:
        assert tracker.get_last_record(f) == expected


def test_get_last_record_across_chunks(tmp_path):
    p = tmp_path / "f"
    p.write_bytes(b"x" * 10000 + b"\n" + b"y" * 5000 + b"\n")
    with open(p, "rb") as f:
        assert tracker.get_last_record(f) == (10001, b"y" * 5000 + b"\n")


def test_save_music_appends(csv, lock):
    tracker.save_music(csv, lock, "Drake", "Mob Ties", 10, "20-12-2024", "20:05:51")
    tracker.save_music(csv, lock, "NF", "The Search", 3, "20-12-2024", "20:05:48")
    assert read(csv) == ["Drake;Mob Ties;10;20-12-2024;20:05:51", "NF;The Search;3;20-12-2024;20:05:48"]
    assert csv.read_bytes().endswith(os.linesep.encode())


def test_save_music_merges_same_song(csv, lock):
    tracker.save_music(csv, lock, "Drake", "Mob Ties", 10, "20-12-2024", "20:05:51")
    tracker.save_music(csv, lock, "Drake", "Mob Ties", 5, "21-12-2024", "08:00:00")
    assert read(csv) == ["Drake;Mob Ties;15;20-12-2024;20:05:51"]   # keeps the first start time


def test_save_music_escapes_separator(csv, lock):
    tracker.save_music(csv, lock, "A;B", "Song; Live", 10, "20-12-2024", "20:05:51")
    assert read(csv) == ["A,B;Song, Live;10;20-12-2024;20:05:51"]


def test_save_music_unicode(csv, lock):
    tracker.save_music(csv, lock, "Björk", "Jóga", 10, "20-12-2024", "20:05:51")
    tracker.save_music(csv, lock, "Björk", "Jóga", 1, "20-12-2024", "20:05:51")
    assert read(csv) == ["Björk;Jóga;11;20-12-2024;20:05:51"]


def test_save_music_never_raises(tmp_path, lock, capsys):
    tracker.save_music(tmp_path, lock, "A", "B", 1, "d", "h")   # a folder, not a file
    assert "Error saving music" in capsys.readouterr().out


def test_save_music_concurrent_writers(csv, lock):
    def write(i):
        for j in range(25):
            tracker.save_music(csv, lock, f"Artist {i}", f"Song {j}", 1, "d", "h")

    threads = [threading.Thread(target=write, args=(i,)) for i in range(4)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert len(read(csv)) == 100
