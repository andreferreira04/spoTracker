"""Everything that talks to the operating system lives here.

The rest of the app only calls these functions, so the tracker, the reports and
the tray code stay testable without Spotify or the Windows APIs.
"""
import os
import subprocess
import sys
import threading
import time
from collections import namedtuple
from pathlib import Path

IS_WINDOWS = sys.platform == "win32"


# ── Now playing ───────────────────────────────────────────────────────────────
NowPlaying = namedtuple("NowPlaying", "artist title playing")
"""What Spotify is doing. `playing` is False while paused or during an ad."""

PAUSED = NowPlaying("", "", False)


def get_now_playing():
    """Return a NowPlaying, or None when Spotify is not running."""
    if IS_WINDOWS:
        return _now_playing_windows()
    return None


# Windows: Spotify shows "Artist - Title" as its window title while playing,
# and "Spotify" / "Spotify Premium" / "Advertisement" otherwise.
def parse_window_title(title):
    if not title or " - " not in title:
        return PAUSED
    artist, _, music = title.partition(" - ")
    return NowPlaying(artist, music, True)


def list_windows():
    """Return (title, exe path or None) for every visible top-level window."""
    import ctypes
    import psutil

    user32 = ctypes.windll.user32
    EnumWindowsProc = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    results = []

    def foreach_window(hwnd, _):
        if user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            buff = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buff, length + 1)
            pid = ctypes.c_ulong()
            user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            try:
                exe = psutil.Process(pid.value).exe()
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess, ValueError):
                exe = None
            results.append((buff.value, exe))
        return True

    user32.EnumWindows(EnumWindowsProc(foreach_window), 0)
    return results


def find_window_title(exe_name, windows=None):
    """Return the title of the first titled window owned by exe_name, or None."""
    for title, exe in windows if windows is not None else list_windows():
        if exe and os.path.basename(exe).lower() == exe_name.lower() and title:
            return title
    return None


def _now_playing_windows():
    title = find_window_title("Spotify.exe")
    return None if title is None else parse_window_title(title)


# ── Folders & launching ───────────────────────────────────────────────────────
def get_documents_folder():
    """Return the user's Documents folder."""
    if IS_WINDOWS:
        import ctypes
        import ctypes.wintypes
        buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
        ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)  # 5 = CSIDL_PERSONAL
        if buf.value:
            return Path(buf.value)
    return Path.home() / "Documents"


def get_data_dir():
    """Folder holding the CSV and the reports. SPOTRACKER_DATA_DIR overrides it (used by tests)."""
    override = os.environ.get("SPOTRACKER_DATA_DIR")
    path = Path(override) if override else get_documents_folder() / "SpoTracker"
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_launch_command(*args, script=None):
    """Command that starts this app again (frozen build or `python music-register.py`)."""
    if getattr(sys, "frozen", False):
        return [sys.executable, *args]
    script = script or str(Path(__file__).with_name("music-register.py"))
    return [sys.executable, os.path.abspath(script), *args]


def background_popen_kwargs():
    """Popen kwargs that start a process without a console window."""
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NO_WINDOW}
    return {"start_new_session": True}


def is_headless():
    """SPOTRACKER_HEADLESS=1 turns dialogs into prints and skips opening the browser (CI, smoke tests)."""
    return os.environ.get("SPOTRACKER_HEADLESS") == "1"


def open_in_browser(path):
    """Open a local file in the default browser."""
    open_in_browser_url(Path(path).as_uri())


def open_in_browser_url(url):
    if is_headless():
        print(f"[headless] would open {url}")
        return
    import webbrowser
    webbrowser.open(url)


def find_chromium_browser():
    """Path to an installed Chrome / Edge / Brave / Chromium, or None.

    The Spotify login drives one of these through the DevTools protocol, which
    Firefox and Safari don't speak.
    """
    import shutil

    if IS_WINDOWS:
        roots = [os.environ.get(v) for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        relatives = [
            r"Google\Chrome\Application\chrome.exe",
            r"Microsoft\Edge\Application\msedge.exe",
            r"BraveSoftware\Brave-Browser\Application\brave.exe",
            r"Chromium\Application\chrome.exe",
        ]
        candidates = [Path(root) / rel for rel in relatives for root in roots if root]
    elif sys.platform == "darwin":
        candidates = [Path(p) for p in (
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
            "/Applications/Chromium.app/Contents/MacOS/Chromium",
        )]
    else:
        names = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                 "microsoft-edge", "microsoft-edge-stable", "brave-browser")
        candidates = [Path(found) for found in map(shutil.which, names) if found]

    return next((str(p) for p in candidates if p.is_file()), None)


# ── Message boxes ─────────────────────────────────────────────────────────────
_WIN_ICONS = {"info": 0x40, "warning": 0x30, "error": 0x10}


def app_icon_path():
    """Path to the SpoTracker logo (.ico), bundled by PyInstaller under assets/."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).parent)) / "assets" / "icon.ico"


def set_window_icon(root):
    """Give a Tk window (and the dialogs it opens) the SpoTracker logo; ignored where .ico is unsupported."""
    try:
        root.iconbitmap(default=str(app_icon_path()))
    except Exception:
        pass


def _win_logo_message_box(title, message):
    """Native MessageBox showing the logo embedded in the frozen exe (PyInstaller stores it as icon resource 1)."""
    import ctypes
    from ctypes import wintypes

    class MSGBOXPARAMSW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT), ("hwndOwner", wintypes.HWND), ("hInstance", wintypes.HINSTANCE),
            ("lpszText", wintypes.LPCWSTR), ("lpszCaption", wintypes.LPCWSTR), ("dwStyle", wintypes.DWORD),
            ("lpszIcon", ctypes.c_void_p), ("dwContextHelpId", ctypes.c_size_t),
            ("lpfnMsgBoxCallback", ctypes.c_void_p), ("dwLanguageId", wintypes.DWORD),
        ]

    get_module = ctypes.windll.kernel32.GetModuleHandleW
    get_module.restype = wintypes.HMODULE
    MB_USERICON = 0x80
    params = MSGBOXPARAMSW(ctypes.sizeof(MSGBOXPARAMSW), None, get_module(None),
                           message, title, MB_USERICON, 1, 0, None, 0)
    if not ctypes.windll.user32.MessageBoxIndirectW(ctypes.byref(params)):
        raise OSError("MessageBoxIndirectW failed")


def show_message(title, message, kind="info"):
    """Show a blocking native message box. kind: "info", "warning" or "error".

    Info messages from the installed app show the SpoTracker logo; warnings and errors keep the system icon.
    """
    if is_headless():
        print(f"[{kind}] {title}: {message}")
        return
    try:
        if IS_WINDOWS:
            import ctypes
            if kind == "info" and getattr(sys, "frozen", False):
                try:
                    _win_logo_message_box(title, message)
                    return
                except Exception:
                    pass  # fall back to the standard box
            ctypes.windll.user32.MessageBoxW(0, message, title, _WIN_ICONS.get(kind, 0x40))
            return
    except Exception:
        pass
    if threading.current_thread() is threading.main_thread():
        try:
            _tk_message(title, message, kind)
            return
        except Exception:
            pass
    print(f"{title}: {message}", file=sys.stderr)


def _tk_message(title, message, kind):
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    set_window_icon(root)
    {"warning": messagebox.showwarning, "error": messagebox.showerror}.get(kind, messagebox.showinfo)(
        title, message, parent=root
    )
    root.destroy()


# ── Cross-process file lock ───────────────────────────────────────────────────
class FileLock:
    """Exclusive lock on a file, shared by threads and processes.

    Serializes CSV writes between the tracker and the Clear Data window (a
    separate process) and keeps a single tracker running.
    """

    def __init__(self, path):
        self.path = Path(path)
        self._fd = None
        self._thread_lock = threading.Lock()

    def _try_lock_fd(self, fd):
        try:
            if IS_WINDOWS:
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def acquire(self, blocking=True, timeout=None):
        if not self._thread_lock.acquire(blocking, -1 if timeout is None else timeout):
            return False
        deadline = None if timeout is None else time.monotonic() + timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o644)
        while not self._try_lock_fd(fd):
            if not blocking or (deadline is not None and time.monotonic() >= deadline):
                os.close(fd)
                self._thread_lock.release()
                return False
            time.sleep(0.05)
        self._fd = fd
        return True

    def release(self):
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            if IS_WINDOWS:
                import msvcrt
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)
            self._thread_lock.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *exc):
        self.release()
