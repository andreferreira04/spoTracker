"""The app as a whole: report generation and each entry point, started as real processes."""
import importlib
import subprocess
import sys
import time

import pytest

from conftest import ROOT, SAMPLE_CSV
from platform_utils import FileLock

MAIN = str(ROOT / "music-register.py")
REPORTS = ["overview.html", "tracks-by-artist.html", "top-artists.html", "stats.html", "share.html", "playlists.html", "logo.png", "spotify.js", "spotify.css"]


def run_app(*args, timeout=120):
    return subprocess.run(
        [sys.executable, MAIN, *args], capture_output=True, text=True, timeout=timeout, cwd=ROOT,
    )


# ── Reports ───────────────────────────────────────────────────────────────────
@pytest.fixture
def get_stats(data_dir):
    """get_stats freshly imported against an empty data folder (it reads paths at import time)."""
    sys.modules.pop("get_stats", None)
    module = importlib.import_module("get_stats")
    yield module
    sys.modules.pop("get_stats", None)


def test_generate_stats(get_stats, data_dir, capsys):
    (data_dir / "music-list.csv").write_text(SAMPLE_CSV, encoding="utf-8")
    get_stats.generate_stats()
    for name in REPORTS:
        assert (data_dir / "reports" / name).exists(), name
    overview = (data_dir / "reports" / "overview.html").read_text(encoding="utf-8")
    assert "{{" not in overview
    out = capsys.readouterr().out
    assert "Report created successfully" in out and "would open" in out


def test_reports_embed_the_data(get_stats, data_dir):
    (data_dir / "music-list.csv").write_text(SAMPLE_CSV, encoding="utf-8")
    get_stats.generate_stats()
    reports = data_dir / "reports"
    stats = (reports / "stats.html").read_text(encoding="utf-8")
    assert "{{ stats_json }}" not in stats and '"totalDaysTracked"' in stats
    assert "Árvore" in (reports / "top-artists.html").read_text(encoding="utf-8")


def test_playlists_page_embeds_history_per_song(get_stats, data_dir):
    import json
    import feats
    (data_dir / "music-list.csv").write_text(SAMPLE_CSV, encoding="utf-8")
    get_stats.generate_stats()
    html = (data_dir / "reports" / "playlists.html").read_text(encoding="utf-8")
    history = json.loads(html.split("const HISTORY = ", 1)[1].split(";\n", 1)[0])
    # Song 3: a 15 s skip and a 240 s play -> 255 s, 1 play, last played on the 15th
    assert history["songs"][feats.song_key("Artist B", "Song 3")] == ["Artist B", "Song 3", 255, 1, "2026-09-15"]
    assert history["totalSeconds"] == 755 and history["since"] == "2026-09-01"
    assert "window.SPOTRACKER_API_PORT = 47815" in html


def test_generate_stats_without_data_warns(get_stats, data_dir, capsys):
    get_stats.generate_stats()
    assert "[warning]" in capsys.readouterr().out
    assert not (data_dir / "reports" / "overview.html").exists()


# ── Entry points ──────────────────────────────────────────────────────────────
def test_entry_generate_report(data_dir):
    (data_dir / "music-list.csv").write_text(SAMPLE_CSV, encoding="utf-8")
    result = run_app("--generate-report")
    assert result.returncode == 0, result.stderr
    for name in REPORTS:
        assert (data_dir / "reports" / name).exists(), name


def test_entry_second_tracker_exits_immediately(data_dir):
    lock = FileLock(data_dir / "spotracker.lock")   # pretend a tracker is already running
    assert lock.acquire(blocking=False)
    try:
        start = time.monotonic()
        result = run_app(timeout=60)
        assert result.returncode == 0, result.stderr
        assert time.monotonic() - start < 30
    finally:
        lock.release()


def test_entry_clear_data_skips_when_window_already_open(data_dir):
    lock = FileLock(data_dir / "clear-data.lock")
    assert lock.acquire(blocking=False)
    try:
        result = run_app("--clear-data", timeout=60)
        assert result.returncode == 0, result.stderr
    finally:
        lock.release()


def test_modules_import_without_windows_apis():
    """No module may touch ctypes.windll at import time, so tests can stub the Windows APIs."""
    code = (
        "import ctypes, sys; sys.path.insert(0, sys.argv[1]);"
        "ctypes.__dict__.pop('windll', None);"   # as on a non-Windows OS
        "import platform_utils, tracker, clear_data, get_stats, version"
    )
    result = subprocess.run([sys.executable, "-c", code, str(ROOT)], capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stderr
