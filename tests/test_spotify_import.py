import json
import zipfile
from datetime import datetime, timedelta, timezone

import pytest

import spotify_import as si
from platform_utils import FileLock


def ext(ts, track, artist="Artist A", ms=200_000, **extra):
    """One entry of the Extended streaming history."""
    return {"ts": ts, "ms_played": ms, "master_metadata_track_name": track,
            "master_metadata_album_artist_name": artist, **extra}


def local_start(ts, ms):
    """What the CSV should hold for an export entry: local start time."""
    end = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    return (end - timedelta(milliseconds=ms)).astimezone().replace(tzinfo=None, microsecond=0)


def csv_line(artist, track, seconds, start):
    return f"{artist};{track};{seconds};{start:%d-%m-%Y};{start:%H:%M:%S}"


def make_zip(path, files):
    with zipfile.ZipFile(path, "w") as zf:
        for name, content in files.items():
            zf.writestr(name, content if isinstance(content, str) else json.dumps(content))
    return path


# ── parse_entry ───────────────────────────────────────────────────────────────
def test_parse_extended_entry_uses_local_start_time():
    r = si.parse_entry(ext("2019-01-01T00:19:54Z", "Trapstar", "LON3R JOHNY", ms=142_947))
    assert r == si.Record(local_start("2019-01-01T00:19:54Z", 142_947), "LON3R JOHNY", "Trapstar", 142)


def test_parse_account_data_entry():
    r = si.parse_entry({"endTime": "2023-05-01 12:00", "artistName": "B", "trackName": "Song", "msPlayed": 60_000})
    assert r.track == "Song" and r.artist == "B" and r.seconds == 60
    end = datetime(2023, 5, 1, 12, 0, tzinfo=timezone.utc)
    assert r.start == (end - timedelta(minutes=1)).astimezone().replace(tzinfo=None)


@pytest.mark.parametrize("entry", [
    ext("2019-01-01T00:19:54Z", None, None, episode_name="Podcast"),  # podcast
    ext("2019-01-01T00:19:54Z", "Song", ms=0),
    ext("not a date", "Song"),
    {"something": "else"},
    "text",
])
def test_parse_ignores_non_plays(entry):
    assert si.parse_entry(entry) is None


@pytest.mark.parametrize("ms, seconds", [(1, 1), (500, 1), (999, 1), (1000, 1), (2999, 2)])
def test_parse_keeps_skips(ms, seconds):
    assert si.parse_entry(ext("2019-01-01T00:19:54Z", "Song", ms=ms)).seconds == seconds


def test_parse_replaces_semicolons():
    r = si.parse_entry(ext("2019-01-01T00:19:54Z", "A; B", "X;Y"))
    assert r.track == "A, B" and r.artist == "X,Y"


# ── read_zip ──────────────────────────────────────────────────────────────────
def test_read_zip_reads_every_history_file(tmp_path):
    z = make_zip(tmp_path / "data.zip", {
        "Spotify Extended Streaming History/Streaming_History_Audio_2019.json": [
            ext("2019-01-02T10:00:00Z", "Second"), ext("2019-01-01T10:00:00Z", "First")],
        "Spotify Extended Streaming History/Streaming_History_Audio_2020.json": [
            ext("2020-01-01T10:00:00Z", "Third"), ext("2020-01-01T11:00:00Z", None, None)],
        "Spotify Extended Streaming History/ReadMeFirst.pdf": "x",
        "Spotify Account Data/Playlist1.json": {"playlists": []},
    })
    records, ignored, files = si.read_zip(z)
    assert [r.track for r in records] == ["First", "Second", "Third"]  # sorted
    assert ignored == 1 and files == 2


def test_read_zip_without_history_fails(tmp_path):
    z = make_zip(tmp_path / "data.zip", {"Playlist1.json": {"playlists": []}})
    with pytest.raises(si.NotAnExportError):
        si.read_zip(z)


def test_read_zip_not_a_zip(tmp_path):
    bad = tmp_path / "data.zip"
    bad.write_text("nope")
    with pytest.raises(si.NotAnExportError):
        si.read_zip(bad)


# ── find_new / merge_lines ────────────────────────────────────────────────────
T0 = datetime(2024, 3, 10, 20, 0, 0)


def rec(track, start, artist="Artist A", seconds=200):
    return si.Record(start, artist, track, seconds)


def test_find_new_skips_plays_within_window():
    lines = [csv_line("Artist A", "Song", 180, T0)]
    new, dup = si.find_new([rec("song ", T0 + timedelta(minutes=2, seconds=50))], lines)
    assert new == [] and dup == 1


def test_find_new_keeps_plays_outside_window():
    lines = [csv_line("Artist A", "Song", 180, T0)]
    new, dup = si.find_new([rec("Song", T0 + timedelta(minutes=3, seconds=1))], lines)
    assert len(new) == 1 and dup == 0


def test_find_new_matches_title_even_with_other_artist():
    lines = [csv_line("Artist A, Artist B", "Song", 180, T0)]
    new, dup = si.find_new([rec("Song", T0, artist="Artist A")], lines)
    assert new == [] and dup == 1


def test_find_new_each_line_matches_once():
    # The same song played twice in a row, but only one play recorded by the tracker
    lines = [csv_line("Artist A", "Song", 30, T0)]
    plays = [rec("Song", T0), rec("Song", T0 + timedelta(seconds=40))]
    new, dup = si.find_new(plays, lines)
    assert dup == 1 and new == [plays[1]]


def test_merge_lines_inserts_in_chronological_order():
    lines = [csv_line("A", "One", 100, T0), csv_line("A", "Three", 100, T0 + timedelta(hours=2)), "broken line"]
    new = [rec("Zero", T0 - timedelta(days=1)), rec("Two", T0 + timedelta(hours=1)), rec("Four", T0 + timedelta(days=1))]
    merged = si.merge_lines(lines, new)
    titles = [line.split(";")[1] if ";" in line else line for line in merged]
    assert titles == ["Zero", "One", "Two", "Three", "broken line", "Four"]


def test_merge_lines_keeps_existing_order():
    # Existing lines slightly out of order stay as they are
    lines = [csv_line("A", "B", 1, T0 + timedelta(minutes=5)), csv_line("A", "C", 1, T0)]
    assert si.merge_lines(lines, []) == lines


# ── import_history ────────────────────────────────────────────────────────────
def test_import_history_end_to_end(tmp_path):
    ts1, ts2 = "2019-01-01T00:19:54Z", "2019-01-01T00:46:04Z"
    z = make_zip(tmp_path / "data.zip", {"Streaming_History_Audio_2019.json": [
        ext(ts1, "Trapstar", "LON3R JOHNY", ms=142_947),
        ext(ts2, "Ano Novo", "Jimmy P", ms=203_400),
    ]})
    csv = tmp_path / "music-list.csv"
    # "Ano Novo" already recorded by the tracker, 20 s off; plus a newer play
    recorded = csv_line("Jimmy P", "Ano Novo", 200, local_start(ts2, 203_400) + timedelta(seconds=20))
    newer = csv_line("X", "Later", 100, datetime(2025, 1, 1, 12, 0, 0))
    csv.write_text(recorded + "\n" + newer + "\n", encoding="utf-8")
    backups = tmp_path / "backups"

    result = si.import_history(z, csv, backups, FileLock(tmp_path / "music-list.lock"))

    assert result == si.ImportResult(added=1, duplicates=1, ignored=0, files=1)
    lines = csv.read_text(encoding="utf-8").splitlines()
    assert lines == [csv_line("LON3R JOHNY", "Trapstar", 142, local_start(ts1, 142_947)), recorded, newer]
    assert len(list(backups.iterdir())) == 1

    # Importing the same file again adds nothing
    again = si.import_history(z, csv, backups, FileLock(tmp_path / "music-list.lock"))
    assert again.added == 0 and again.duplicates == 2
    assert csv.read_text(encoding="utf-8").splitlines() == lines


def test_import_history_without_csv(tmp_path):
    z = make_zip(tmp_path / "data.zip", {"Streaming_History_Audio_2019.json": [ext("2019-01-01T00:19:54Z", "Song")]})
    csv = tmp_path / "data" / "music-list.csv"
    result = si.import_history(z, csv, tmp_path / "backups", FileLock(tmp_path / "music-list.lock"))
    assert result.added == 1 and len(csv.read_text(encoding="utf-8").splitlines()) == 1


# ── Report notice / Settings summary ──────────────────────────────────────────
def test_history_days():
    import get_stats
    entries = [get_stats.TrackEntry("A", "B", 10, d, "10:00:00") for d in ("05-03-2026", "20-01-2026", "bad")]
    assert get_stats.history_days(entries, today=datetime(2026, 3, 1).date()) == 40
    assert get_stats.history_days([], today=datetime(2026, 3, 1).date()) == 0


def test_import_summary():
    import settings_window
    text = settings_window.import_summary(si.ImportResult(added=1234, duplicates=5, ignored=0, files=3))
    assert text == "1,234 plays added from 3 files.\n5 were already recorded and were skipped."


def test_import_history_reports_progress(tmp_path):
    z = make_zip(tmp_path / "data.zip", {
        "Streaming_History_Audio_2019.json": [ext("2019-01-01T00:19:54Z", "One")],
        "Streaming_History_Audio_2020.json": [ext("2020-01-01T00:19:54Z", "Two")],
    })
    steps = []
    si.import_history(z, tmp_path / "music-list.csv", tmp_path / "backups",
                      FileLock(tmp_path / "music-list.lock"), progress=lambda f, t: steps.append((f, t)))
    fractions = [f for f, _ in steps]
    assert fractions == sorted(fractions) and fractions[-1] == 1.0
    texts = [t for _, t in steps]
    assert "Reading file 1 of 2…" in texts and "Reading file 2 of 2…" in texts
    assert any(t.startswith("Saving 2 new plays") for t in texts)
