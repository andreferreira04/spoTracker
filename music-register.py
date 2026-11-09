import os
import subprocess
import sys
import threading
import time

import platform_utils as pu
import tracker
from version import VERSION, APP_NAME


save_dir = pu.get_data_dir()

musicListFile = save_dir / "music-list.csv"
backupDir = save_dir / "backups"
csvLock = pu.FileLock(save_dir / "music-list.lock")  # serializes writes between the tracker and Clear Data (another process)
instanceLock = pu.FileLock(save_dir / "spotracker.lock")
timeSleep = 1


def saveMusic(artist, music, secondsListen, date, hour):
    tracker.save_music(musicListFile, csvLock, artist, music, secondsListen, date, hour)


# ── Actions launched from the tray ───────────────────────────────────────────
def launch_self(flag, what):
    """Run this app again with a flag (--generate-report, --clear-data) as a separate process."""
    try:
        subprocess.Popen(pu.get_launch_command(flag, script=__file__), **pu.background_popen_kwargs())
    except Exception as e:
        pu.show_message(APP_NAME, f"Failed to {what}:\n{e}", "error")


def generate_report(_=None):
    """Launch the stats report generator as a subprocess."""
    launch_self("--generate-report", "generate report")


def open_report(_=None):
    """Open the existing report in the browser, or generate it first if missing."""
    report = save_dir / "reports" / "overview.html"
    if report.exists():
        pu.open_in_browser(report)
    else:
        generate_report()


def open_clear_data(_=None):
    """Open the Clear Data window in its own process so the tray stays responsive."""
    launch_self("--clear-data", "open Clear Data")


_tracker = tracker.Tracker(saveMusic)


def quit_app(icon):
    """Save the song being played, stop the tray icon and exit."""
    _tracker.stop(time.time())
    icon.stop()
    os._exit(0)


_update_available = False
_tray_icon = None

def check_for_updates():
    """Check GitHub releases for a newer version and set the update flag."""
    global _update_available
    import json
    from urllib.request import urlopen, Request
    from urllib.error import URLError

    REPO = "andreferreira04/spotify-tracker"
    API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

    try:
        req = Request(API_URL, headers={"Accept": "application/vnd.github.v3+json"})
        with urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode())

        latest_tag = data.get("tag_name", "")
        latest_version = latest_tag.lstrip("v")

        if not latest_version or latest_version == VERSION:
            return

        def parse_ver(v):
            try:
                return tuple(int(x) for x in v.split("."))
            except ValueError:
                return (0,)

        if parse_ver(latest_version) > parse_ver(VERSION):
            _update_available = True
            if _tray_icon:
                _tray_icon.update_menu()
            download_url = "https://www.spotracker.eu"
            msg = (
                f"New version available: v{latest_version}\n"
                f"Current version: v{VERSION}\n\n"
                f"Download at:\n{download_url}"
            )
            pu.show_message(f"{APP_NAME} - Update", msg, "info")
    except (URLError, OSError, json.JSONDecodeError, KeyError):
        pass


# ── Tracking loop (runs in background thread) ────────────────────────────────
def tracking_loop():
    while True:
        try:
            state = pu.get_now_playing()
        except Exception:
            state = None
        if _tracker.update(state, time.time()):
            print("Artist: " + _tracker.artist)
            print("Music: " + _tracker.music)
            print("-" * 40)
        time.sleep(timeSleep)


# ── System Tray Icon ─────────────────────────────────────────────────────────
def create_tray_icon():
    """Create a green music-note icon for the system tray."""
    from PIL import Image, ImageDraw

    # 64x64 icon with a Spotify-green gradient circle and a music note
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Circle background
    draw.ellipse([2, 2, size - 3, size - 3], fill=(30, 215, 96))

    # Simple music note shape using basic drawing
    # Note head (filled ellipse)
    draw.ellipse([16, 36, 28, 46], fill="white")
    # Stem
    draw.rectangle([26, 14, 29, 40], fill="white")
    # Flag
    draw.polygon([(29, 14), (42, 20), (42, 28), (29, 22)], fill="white")
    # Second note head
    draw.ellipse([34, 32, 46, 42], fill="white")
    # Second stem
    draw.rectangle([44, 10, 47, 36], fill="white")
    # Beam connecting stems
    draw.rectangle([26, 12, 47, 16], fill="white")

    return img


def run_tray():
    """Set up and run the system tray icon with menu."""
    import pystray

    icon_image = create_tray_icon()

    menu = pystray.Menu(
        pystray.MenuItem("Open Report", open_report, default=True),
        pystray.MenuItem("Generate New Report", generate_report),
        pystray.MenuItem("Clear Data…", open_clear_data),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Update", lambda _: pu.open_in_browser_url("https://www.spotracker.eu/"), visible=lambda _: _update_available),
        pystray.MenuItem("Exit", quit_app),
    )

    global _tray_icon
    icon = pystray.Icon("SpoTracker", icon_image, APP_NAME, menu)
    _tray_icon = icon

    # Start the tracking loop in a daemon thread
    tracker_thread = threading.Thread(target=tracking_loop, daemon=True)
    tracker_thread.start()

    # Local API the reports use for the Spotify login and artist pages
    import spotify_api
    if not spotify_api.start_server():
        print(f"Spotify API port {spotify_api.PORT} is busy; Spotify features in the reports are off.")

    # Check for updates in a background thread (non-blocking)
    update_thread = threading.Thread(target=check_for_updates, daemon=True)
    update_thread.start()

    # Run the tray icon on the main thread (blocks until icon.stop())
    icon.run()


def self_test():
    """Import everything the frozen build needs on this OS and query Spotify once (used by smoke_test.py)."""
    import pystray  # loads the platform tray backend
    import tkinter
    import get_stats
    import clear_data
    print("tray backend:", pystray.Icon.__module__)
    print("now playing:", pu.get_now_playing())
    return 0


# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if "--self-test" in sys.argv:
        sys.exit(self_test())
    elif "--generate-report" in sys.argv:
        # Called from the tray or a Start Menu shortcut — just generate the report and exit
        import get_stats
        get_stats.generate_stats()
    elif "--clear-data" in sys.argv:
        import clear_data
        clear_data.open_dialog(musicListFile, backupDir, csvLock, pu.FileLock(save_dir / "clear-data.lock"))
    else:
        if not instanceLock.acquire(blocking=False):
            sys.exit(0)  # another tracker is already running
        run_tray()
