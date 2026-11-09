"""Smoke test for the built SpoTracker.

Run after: pyinstaller music-register.spec --noconfirm
    python smoke_test.py [--skip-tray]

Uses a temporary data folder, so your real data is never touched.
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import platform_utils as pu

ROOT = Path(__file__).resolve().parent
SAMPLE = "Artist A;Song 1;200;01-09-2026;10:00:00\nArtist B;Song 2;240;15-09-2026;12:00:00\n"


def find_executable():
    return ROOT / "dist" / "SpoTracker" / "SpoTracker.exe"


def check(name, ok, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}: {name}{' — ' + detail if detail and not ok else ''}", flush=True)
    if not ok:
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-tray", action="store_true", help="skip starting the tray (no desktop session)")
    args = parser.parse_args()

    exe = find_executable()
    check(f"executable exists ({exe})", exe.exists(), "run pyinstaller first")

    data = Path(tempfile.mkdtemp(prefix="spotracker-smoke-"))
    env = dict(os.environ, SPOTRACKER_DATA_DIR=str(data), SPOTRACKER_HEADLESS="1")

    def run(*flags, timeout=120):
        return subprocess.run([str(exe), *flags], env=env, capture_output=True, text=True, timeout=timeout)

    # Every module is bundled and loads
    result = run("--self-test")
    check("--self-test (bundled imports, tray backend, Spotify query)", result.returncode == 0, result.stderr[-2000:])

    # Report generation
    (data / "music-list.csv").write_text(SAMPLE, encoding="utf-8")
    result = run("--generate-report")
    reports = [data / "reports" / n for n in ("overview.html", "tracks-by-artist.html", "top-artists.html", "stats.html", "share.html", "playlists.html", "logo.png", "spotify.js", "spotify.css")]
    missing = [p.name for p in reports if not p.exists()]
    check("--generate-report", result.returncode == 0 and not missing, f"exit {result.returncode}, missing {missing}\n{result.stderr[-2000:]}")

    # Single instance: with the lock held, a second tracker must exit straight away
    lock = pu.FileLock(data / "spotracker.lock")
    lock.acquire()
    try:
        start = time.monotonic()
        result = run(timeout=60)
        check("second instance exits", result.returncode == 0 and time.monotonic() - start < 30, result.stderr[-2000:])
    finally:
        lock.release()

    # Tray mode keeps running
    if not args.skip_tray:
        proc = subprocess.Popen([str(exe)], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        time.sleep(5)
        alive = proc.poll() is None
        proc.kill()
        _, err = proc.communicate()
        check("tray mode starts and keeps running", alive, f"exit {proc.returncode}\n{err[-2000:]}")

    print("\nAll smoke tests passed!")


if __name__ == "__main__":
    main()
