import os
import subprocess
import sys
import threading
import time

import platform_utils as pu
import settings
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


def open_settings(_=None):
    """Open the Settings window in its own process so the tray stays responsive."""
    launch_self("--settings", "open Settings")


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
_tracking_enabled = True


def is_tracking_enabled(_=None):
    return _tracking_enabled


TOOLTIP_MAX = 127  # Windows limits tray tooltips to 128 characters


def tray_status(enabled, state, error=False):
    """Tooltip text for the tray icon: what is being tracked right now."""
    if not enabled:
        text = "Tracking paused"
    elif error:
        text = "Can't read Spotify"
    elif state is None:
        text = "Spotify is not open"
    elif not state.playing or not state.title:
        text = "Spotify paused"
    else:
        text = f"{state.artist} – {state.title}" if state.artist else f"{state.title}"
    full = f"{APP_NAME}\n{text}"
    return full if len(full) <= TOOLTIP_MAX else full[:TOOLTIP_MAX - 1] + "…"


def set_tray_status(text):
    """Update the tray tooltip, only when it changed (the loop calls this every second)."""
    if _tray_icon is not None and _tray_icon.title != text:
        _tray_icon.title = text


def initial_tracking_state():
    """Tracking starts on, unless "remember tracking state" is set and it was off when the app closed."""
    s = settings.load()
    return s["tracking_enabled"] or not s["remember_tracking_state"]


def toggle_tracking(icon=None, _=None):
    """Turn tracking on/off from the tray. The loop saves the current song on its next tick."""
    global _tracking_enabled
    _tracking_enabled = not _tracking_enabled
    try:
        settings.update(tracking_enabled=_tracking_enabled)  # always saved; only used if remembering is on
    except OSError:
        pass
    if icon is not None:
        icon.icon = create_tray_icon(grey=not _tracking_enabled)
        if not _tracking_enabled:
            icon.title = tray_status(False, None)
        icon.update_menu()


def tracking_tick(now):
    """One iteration of the tracking loop."""
    if not _tracking_enabled:
        # Save what was playing up to the moment tracking was turned off, then stay idle
        _tracker.stop(now)
        set_tray_status(tray_status(False, None))
        return
    error = False
    try:
        state = pu.get_now_playing()
    except Exception:
        state, error = None, True
    set_tray_status(tray_status(True, state, error))
    if _tracker.update(state, now):
        print("Artist: " + _tracker.artist)
        print("Music: " + _tracker.music)
        print("-" * 40)


def tracking_loop():
    while True:
        tracking_tick(time.time())
        time.sleep(timeSleep)


# ── System Tray Icon ─────────────────────────────────────────────────────────
def create_tray_icon(grey=False):
    """Load the SpoTracker logo (assets/icon.ico, bundled by PyInstaller) for the system tray.

    grey=True returns a faded greyscale version, shown while tracking is paused.
    """
    from PIL import Image

    img = Image.open(pu.app_icon_path())
    img.size = (64, 64)  # pick the 64px frame of the .ico
    img = img.convert("RGBA")
    if grey:
        lum = img.convert("L")
        alpha = img.getchannel("A").point(lambda v: v * 6 // 10)
        img = Image.merge("RGBA", (lum, lum, lum, alpha))
    return img


def run_tray():
    """Set up and run the system tray icon with menu."""
    import pystray

    icon_image = create_tray_icon()

    menu = pystray.Menu(
        pystray.MenuItem("Open Report", open_report, default=True),
        pystray.MenuItem("Generate New Report", generate_report),
        pystray.MenuItem("Clear Data…", open_clear_data),
        pystray.MenuItem("Settings", open_settings),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Tracking", toggle_tracking, checked=is_tracking_enabled),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Update", lambda _: pu.open_in_browser_url("https://www.spotracker.eu/"), visible=lambda _: _update_available),
        pystray.MenuItem("Exit", quit_app),
    )

    global _tray_icon, _tracking_enabled
    _tracking_enabled = initial_tracking_state()
    if not _tracking_enabled:
        icon_image = create_tray_icon(grey=True)
    icon = pystray.Icon("SpoTracker", icon_image, tray_status(_tracking_enabled, None), menu)
    _tray_icon = icon

    # Start the tracking loop in a daemon thread
    tracker_thread = threading.Thread(target=tracking_loop, daemon=True)
    tracker_thread.start()

    # Local API the reports use for the Spotify login and artist pages
    import spotify_api
    if not spotify_api.start_server():
        print(f"Spotify API port {spotify_api.PORT} is busy; Spotify features in the reports are off.")

    # Check for updates in a background thread (non-blocking)
    if settings.load()["check_for_updates"]:
        threading.Thread(target=check_for_updates, daemon=True).start()

    # Run the tray icon on the main thread (blocks until icon.stop())
    icon.run()


def self_test():
    """Import everything the frozen build needs on this OS and query Spotify once (used by smoke_test.py)."""
    import pystray  # loads the platform tray backend
    import tkinter
    import get_stats
    import clear_data
    import settings_window
    print("tray backend:", pystray.Icon.__module__)
    print("tray icon:", create_tray_icon().size)  # fails if assets/icon.ico was not bundled
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
    elif "--settings" in sys.argv:
        import settings_window

        def regenerate():
            import get_stats  # imported here: it reads the settings when imported
            get_stats.generate_stats()
        settings_window.open_dialog(pu.FileLock(save_dir / "settings-window.lock"), regenerate)
    elif "--clear-data" in sys.argv:
        import clear_data
        clear_data.open_dialog(musicListFile, backupDir, csvLock, pu.FileLock(save_dir / "clear-data.lock"))
    else:
        if not instanceLock.acquire(blocking=False):
            sys.exit(0)  # another tracker is already running
        run_tray()
