"""Clear Data helpers (the Tk window itself is covered by the entry point tests)."""
import os
from datetime import datetime

import pytest

import clear_data
from conftest import SAMPLE_CSV
from platform_utils import FileLock


@pytest.fixture
def csv(tmp_path):
    p = tmp_path / "music-list.csv"
    p.write_text(SAMPLE_CSV, encoding="utf-8")
    return p


@pytest.fixture
def lock(tmp_path):
    return FileLock(tmp_path / "music-list.lock")


def test_read_lines(csv, tmp_path):
    lines = clear_data.read_lines(csv)
    assert len(lines) == 5 and lines[0] == "Artist A;Song 1;200;01-09-2026;10:00:00"
    assert clear_data.read_lines(tmp_path / "missing.csv") == []


def test_matches():
    assert clear_data.matches("A;B;1;d;h", lambda p: p[0] == "A")
    assert not clear_data.matches("A;B;1;d;h", lambda p: p[0] == "X")
    assert not clear_data.matches("broken line", lambda p: True)


def test_line_size():
    assert clear_data.line_size("ação") == len("ação".encode("utf-8")) + len(os.linesep)


@pytest.mark.parametrize("size, text", [(0, "0.0 KB"), (1536, "1.5 KB"), (3 * 1024 * 1024, "3.00 MB")])
def test_format_size(size, text):
    assert clear_data.format_size(size) == text


def test_remove_records_by_artist(csv, lock, tmp_path):
    backups = tmp_path / "backups"
    removed = clear_data.remove_records(csv, backups, lock, lambda p: p[0] == "Artist B")
    assert removed == 2
    assert [l.split(";")[0] for l in clear_data.read_lines(csv)] == ["Artist A", "Artist A", "Árvore"]
    (backup,) = backups.iterdir()
    assert backup.name.startswith("music-list-") and backup.read_text(encoding="utf-8") == SAMPLE_CSV


def test_remove_records_before_date(csv, lock, tmp_path):
    cutoff = datetime(2026, 9, 10)
    removed = clear_data.remove_records(
        csv, tmp_path / "b", lock, lambda p: datetime.strptime(p[3], "%d-%m-%Y") < cutoff
    )
    assert removed == 3


def test_remove_nothing_makes_no_backup(csv, lock, tmp_path):
    assert clear_data.remove_records(csv, tmp_path / "b", lock, lambda p: False) == 0
    assert not (tmp_path / "b").exists()
    assert csv.read_text(encoding="utf-8") == SAMPLE_CSV


def test_remove_all(csv, lock, tmp_path):
    assert clear_data.remove_records(csv, tmp_path / "b", lock, lambda p: True) == 5
    assert clear_data.read_lines(csv) == []
    assert not csv.with_suffix(".tmp").exists()


def test_open_dialog_skips_when_already_open(csv, lock, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr(clear_data, "_run_dialog", lambda *a: opened.append(a))
    dialog_lock = FileLock(tmp_path / "clear-data.lock")

    other_window = FileLock(tmp_path / "clear-data.lock")
    assert other_window.acquire(blocking=False)
    clear_data.open_dialog(csv, tmp_path / "b", lock, dialog_lock)
    assert opened == []
    other_window.release()

    clear_data.open_dialog(csv, tmp_path / "b", lock, dialog_lock)
    assert len(opened) == 1
    assert dialog_lock.acquire(blocking=False)   # released after the window closed
    dialog_lock.release()
