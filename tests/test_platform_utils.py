"""Folders, launching, dialogs and file locks."""
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

import platform_utils as pu


# ── Folders ───────────────────────────────────────────────────────────────────
def test_data_dir_override(tmp_path, monkeypatch):
    target = tmp_path / "custom" / "SpoTracker"
    monkeypatch.setenv("SPOTRACKER_DATA_DIR", str(target))
    assert pu.get_data_dir() == target
    assert target.is_dir()


def test_data_dir_default_is_documents(tmp_path, monkeypatch):
    monkeypatch.delenv("SPOTRACKER_DATA_DIR")
    monkeypatch.setattr(pu, "get_documents_folder", lambda: tmp_path)
    assert pu.get_data_dir() == tmp_path / "SpoTracker"


def test_documents_folder_exists_on_this_machine():
    folder = pu.get_documents_folder()
    assert folder.is_absolute()
    assert folder.exists()


# ── Launching ─────────────────────────────────────────────────────────────────
def test_launch_command_from_source(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    cmd = pu.get_launch_command("--generate-report")
    assert cmd[0] == sys.executable
    assert Path(cmd[1]) == Path(pu.__file__).with_name("music-register.py").resolve()
    assert cmd[2:] == ["--generate-report"]


def test_launch_command_frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert pu.get_launch_command("--clear-data") == [sys.executable, "--clear-data"]


@pytest.mark.skipif(sys.platform != "win32", reason="Windows only")
def test_background_popen_kwargs():
    assert pu.background_popen_kwargs() == {"creationflags": subprocess.CREATE_NO_WINDOW}


def test_background_popen_kwargs_really_start_a_process():
    proc = subprocess.Popen([sys.executable, "-c", "pass"], **pu.background_popen_kwargs())
    assert proc.wait(timeout=30) == 0


def test_open_in_browser_headless(capsys, tmp_path, monkeypatch):
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    pu.open_in_browser(tmp_path / "overview.html")
    assert opened == []
    assert "overview.html" in capsys.readouterr().out


def test_open_in_browser(tmp_path, monkeypatch):
    monkeypatch.delenv("SPOTRACKER_HEADLESS")
    opened = []
    monkeypatch.setattr("webbrowser.open", opened.append)
    pu.open_in_browser(tmp_path / "overview.html")
    pu.open_in_browser_url("https://www.spotracker.eu/")
    assert opened == [(tmp_path / "overview.html").as_uri(), "https://www.spotracker.eu/"]


# ── Message boxes ─────────────────────────────────────────────────────────────
def test_message_headless_prints(capsys):
    pu.show_message("Title", "Body", "warning")
    assert capsys.readouterr().out.strip() == "[warning] Title: Body"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows MessageBox")
def test_windows_message_box(monkeypatch):
    import ctypes
    monkeypatch.delenv("SPOTRACKER_HEADLESS")
    calls = []
    monkeypatch.setattr(ctypes.windll.user32, "MessageBoxW", lambda *a: calls.append(a))
    pu.show_message("T", "M", "error")
    assert calls == [(0, "M", "T", 0x10)]


# ── File lock ─────────────────────────────────────────────────────────────────
HOLD_LOCK = """
import sys, time
sys.path.insert(0, sys.argv[1])
import platform_utils as pu
lock = pu.FileLock(sys.argv[2])
assert lock.acquire(blocking=False)
print("locked", flush=True)
time.sleep(float(sys.argv[3]))
lock.release()
"""


def _hold_in_other_process(path, seconds):
    proc = subprocess.Popen(
        [sys.executable, "-c", HOLD_LOCK, str(Path(pu.__file__).parent), str(path), str(seconds)],
        stdout=subprocess.PIPE, text=True,
    )
    assert proc.stdout.readline().strip() == "locked"
    return proc


def test_lock_acquire_release(tmp_path):
    lock = pu.FileLock(tmp_path / "sub" / "x.lock")
    assert lock.acquire(blocking=False)
    lock.release()
    assert lock.acquire(blocking=False)
    lock.release()
    lock.release()  # releasing twice is harmless


def test_lock_excludes_other_processes(tmp_path):
    path = tmp_path / "x.lock"
    proc = _hold_in_other_process(path, 30)
    try:
        lock = pu.FileLock(path)
        assert not lock.acquire(blocking=False)
        start = time.monotonic()
        assert not lock.acquire(timeout=0.3)
        assert time.monotonic() - start >= 0.25
    finally:
        proc.kill()
        proc.wait()
    assert pu.FileLock(path).acquire(timeout=5)


def test_lock_waits_for_other_process(tmp_path):
    path = tmp_path / "x.lock"
    proc = _hold_in_other_process(path, 0.5)
    lock = pu.FileLock(path)
    assert lock.acquire(timeout=20)
    lock.release()
    proc.wait()


def test_lock_serializes_threads(tmp_path):
    lock = pu.FileLock(tmp_path / "x.lock")
    inside, overlaps = [0], []

    def work():
        for _ in range(20):
            with lock:
                inside[0] += 1
                overlaps.append(inside[0])
                time.sleep(0.001)
                inside[0] -= 1

    threads = [threading.Thread(target=work) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert max(overlaps) == 1 and len(overlaps) == 80


def test_two_lock_objects_in_one_process_exclude_each_other(tmp_path):
    a, b = pu.FileLock(tmp_path / "x.lock"), pu.FileLock(tmp_path / "x.lock")
    assert a.acquire(blocking=False)
    assert not b.acquire(blocking=False)
    a.release()
    assert b.acquire(blocking=False)
    b.release()
