from __future__ import print_function
import ctypes
import ctypes.wintypes
from datetime import datetime
from pathlib import Path
import time
import os.path
import psutil
import sys
import os
import threading

VERSION = "0.0.0"


def get_documents_folder() -> Path:
    """Return the real Documents folder using the Windows Shell API."""
    buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
    ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)  # 5 = CSIDL_PERSONAL
    return Path(buf.value)


save_dir = get_documents_folder() / "SpoTracker"
save_dir.mkdir(parents=True, exist_ok=True)

musicListFile = save_dir / "music-list.csv"
timeSleep = 1

def getProcessTitles(): 
    EnumWindows = ctypes.windll.user32.EnumWindows
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int), ctypes.POINTER(ctypes.c_int))
    GetWindowText = ctypes.windll.user32.GetWindowTextW
    GetWindowTextLength = ctypes.windll.user32.GetWindowTextLengthW
    IsWindowVisible = ctypes.windll.user32.IsWindowVisible
    GetWindowThreadProcessId = ctypes.windll.user32.GetWindowThreadProcessId

    results = []
    
    def foreach_window(hwnd, lParam):
        if IsWindowVisible(hwnd):
            length = GetWindowTextLength(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            GetWindowText(hwnd, buff, length + 1)
            title = buff.value
            
            pid = ctypes.c_ulong()
            GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            
            try:
                process = psutil.Process(pid.value)
                exe = process.exe()
                results.append((title, exe))
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                results.append((title, None))
                
        return True

    EnumWindows(EnumWindowsProc(foreach_window), 0)
    return results

def getSpotifyTitle():
    exesTitles = getProcessTitles()
    for title, exe in exesTitles:
        if exe and isinstance(exe, str) and (exe.split("\\")[-1] == "Spotify.exe"):
            if (title != "None"):
                return title
    return None

def saveMusic(artist, music, secondsListen, date, hour):
    try:
        music = music.replace(";", ",")
        with open(musicListFile, "a", encoding="utf-8") as f:
            f.write(f"{artist};{music};{secondsListen};{date};{hour}\n")
    except:
        print("Error saving music in file", musicListFile)

def isAlreadyRunning():
    currentPid = os.getpid()
    processName = os.path.basename(sys.argv[0])

    for proc in psutil.process_iter(['pid', 'name']):
        if proc.info['pid'] != currentPid and proc.info['name'] == processName:
            return True
    return False

if "--generate-report" not in sys.argv and isAlreadyRunning():
    sys.exit(0)


# ── Report generation ────────────────────────────────────────────────────────
def generate_report(_=None):
    """Launch the stats report generator as a subprocess."""
    import subprocess
    try:
        subprocess.Popen(
            [sys.executable, "--generate-report"],
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except Exception as e:
        ctypes.windll.user32.MessageBoxW(
            0, f"Failed to generate report:\n{e}", "SpoTracker", 0x10
        )


def open_report(_=None):
    """Open the existing report in the browser, or generate it first if missing."""
    import webbrowser
    report = save_dir / "reports" / "overview.html"
    if report.exists():
        webbrowser.open(report.as_uri())
    else:
        generate_report()


def quit_app(icon):
    """Stop the tray icon and exit."""
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
            ctypes.windll.user32.MessageBoxW(0, msg, "SpoTracker - Update", 0x40)
    except (URLError, OSError, json.JSONDecodeError, KeyError):
        pass


# ── Tracking loop (runs in background thread) ────────────────────────────────
def tracking_loop():
    previousArtist = ""
    previousMusic = ""
    previousDate = None
    previousHour = None
    musicStart = None
    totalPauseTime = 0
    pauseStart = None        # timestamp when pause began (None = not paused)

    while True:
        processTitle = getSpotifyTitle()

        # Spotify not running
        if processTitle is None:
            # Save the song that was playing before Spotify closed
            if musicStart is not None and previousArtist and previousMusic:
                secondsListened = int(time.time() - musicStart - totalPauseTime)
                saveMusic(previousArtist, previousMusic, secondsListened, previousDate, previousHour)
            musicStart = None
            totalPauseTime = 0
            pauseStart = None
            previousArtist = ""
            previousMusic = ""
            time.sleep(timeSleep)
            continue

        # Paused / Ads
        if " - " not in processTitle:
            if pauseStart is None:
                pauseStart = time.time()
            time.sleep(timeSleep)
            continue

        # Music Playing
        if pauseStart is not None:
            totalPauseTime += time.time() - pauseStart
            pauseStart = None

        titleDivided = processTitle.split(" - ")

        if len(titleDivided) == 2:
            artist, music = titleDivided
        else:
            artist = titleDivided[0]
            music = " - ".join(titleDivided[1:])

        # Song changed
        if not (artist == previousArtist and music == previousMusic):
            if musicStart is not None and previousArtist and previousMusic:
                secondsListened = int(time.time() - musicStart - totalPauseTime)
                saveMusic(previousArtist, previousMusic, secondsListened, previousDate, previousHour)

            previousArtist = artist
            previousMusic = music
            previousDate = datetime.today().strftime('%d-%m-%Y')
            previousHour = datetime.today().strftime("%H:%M:%S")
            musicStart = time.time()
            totalPauseTime = 0
            print("Artist: " + artist)
            print("Music: " + music)
            print("-" * 40)
        time.sleep(timeSleep)


# ── System Tray Icon ─────────────────────────────────────────────────────────
def create_tray_icon():
    """Create a green music-note icon for the system tray."""
    from PIL import Image, ImageDraw, ImageFont

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
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Update", lambda _: __import__('webbrowser').open("https://www.spotracker.eu/"), visible=lambda _: _update_available),
        pystray.MenuItem("Exit", quit_app),
    )

    global _tray_icon
    icon = pystray.Icon("SpoTracker", icon_image, "SpoTracker", menu)
    _tray_icon = icon

    # Start the tracking loop in a daemon thread
    tracker_thread = threading.Thread(target=tracking_loop, daemon=True)
    tracker_thread.start()

    # Check for updates in a background thread (non-blocking)
    update_thread = threading.Thread(target=check_for_updates, daemon=True)
    update_thread.start()

    # Run the tray icon on the main thread (blocks until icon.stop())
    icon.run()


# ── Entry point ──────────────────────────────────────────────────────────────
if "--generate-report" in sys.argv:
    # Called from Start Menu shortcut — just generate the report and exit
    import get_stats
    get_stats.generate_stats()
else:
    run_tray()