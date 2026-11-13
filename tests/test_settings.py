"""settings.json: defaults, validation, merging writes, and their effect on the reports."""
import importlib
import json
import sys

import pytest

import settings
import settings_window
from conftest import SAMPLE_CSV


@pytest.fixture(autouse=True)
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("SPOTRACKER_DATA_DIR", str(tmp_path))
    return tmp_path


def test_defaults_when_there_is_no_file():
    assert settings.load() == settings.DEFAULTS


@pytest.mark.parametrize("content", ["not json", "[1, 2]", ""])
def test_broken_file_falls_back_to_defaults(data_dir, content):
    (data_dir / "settings.json").write_text(content, encoding="utf-8")
    assert settings.load() == settings.DEFAULTS


def test_invalid_values_are_ignored_or_clamped():
    values = settings.validate({
        "min_listen_seconds": "30",      # wrong type -> default
        "recent_days": 9999,             # clamped to the max
        "check_for_updates": 0,          # not a bool -> default
        "low_perc_threshold": 80, "high_perc_threshold": 50,  # high raised to low
        "unknown": 1,
    })
    assert values["min_listen_seconds"] == 20
    assert values["recent_days"] == 365
    assert values["check_for_updates"] is True
    assert values["high_perc_threshold"] == 80
    assert "unknown" not in values


def test_update_keeps_the_other_settings(data_dir):
    settings.update(min_listen_seconds=45)
    settings.update(tracking_enabled=False)    # e.g. the tray, from another process
    saved = json.loads((data_dir / "settings.json").read_text(encoding="utf-8"))
    assert saved["min_listen_seconds"] == 45 and saved["tracking_enabled"] is False


def test_update_rejects_unknown_settings():
    with pytest.raises(KeyError):
        settings.update(nope=1)


# ── Settings window form ──────────────────────────────────────────────────────
def test_parse_form_accepts_valid_values():
    values, error = settings_window.parse_form({"min_listen_seconds": " 30 ", "check_for_updates": False})
    assert error is None and values == {"min_listen_seconds": 30, "check_for_updates": False}


@pytest.mark.parametrize("raw, message", [
    ({"min_listen_seconds": "abc"}, "whole number"),
    ({"recent_days": "0"}, "between 1 and 365"),
    ({"low_perc_threshold": "60", "high_perc_threshold": "40"}, "can't be lower"),
])
def test_parse_form_rejects_invalid_values(raw, message):
    values, error = settings_window.parse_form(raw)
    assert values is None and message in error


def test_every_setting_in_the_window_exists():
    shown = [name for _, rows in settings_window.SECTIONS for name, _, _ in rows]
    assert set(shown) <= set(settings.SPEC) and len(shown) == len(set(shown))


# ── Effect on the reports ─────────────────────────────────────────────────────
def generate(data_dir):
    (data_dir / "music-list.csv").write_text(SAMPLE_CSV, encoding="utf-8")
    sys.modules.pop("get_stats", None)
    get_stats = importlib.import_module("get_stats")
    try:
        get_stats.generate_stats()
    finally:
        sys.modules.pop("get_stats", None)
    return data_dir / "reports"


def test_reports_use_the_settings(data_dir):
    settings.update(min_listen_seconds=200, high_perc_threshold=90, recent_days=14,
                    forgotten_days=120, forgotten_min_plays=3)
    reports = generate(data_dir)

    tracks = (reports / "tracks-by-artist.html").read_text(encoding="utf-8")
    all_tracks = json.loads(tracks.split("const ALL_TRACKS = ", 1)[1].split(";\n", 1)[0])
    # Song 1 has a 200 s record: with a 200 s minimum it no longer counts as a play
    song1 = next(t for t in all_tracks if t["track"] == "Song 1")
    assert song1["validPlays"] == 0
    assert "const HIGH_PERC_THRESHOLD = 90;" in tracks and "last 14 days" in tracks

    assert "Last 14 days" in (reports / "stats.html").read_text(encoding="utf-8")
    playlists = (reports / "playlists.html").read_text(encoding="utf-8")
    assert "const FORGOTTEN_DAYS = 120;" in playlists and "const FORGOTTEN_MIN_PLAYS = 3;" in playlists

    for page in reports.glob("*.html"):
        assert "{{" not in page.read_text(encoding="utf-8"), page.name
