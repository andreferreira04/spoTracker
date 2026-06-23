import ctypes
import ctypes.wintypes
import json
import sys
import webbrowser
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path
import os

# ── Paths ─────────────────────────────────────────────────────────────────────
def get_documents_folder() -> Path:
    """Return the real Documents folder using the Windows Shell API."""
    buf = ctypes.create_unicode_buffer(ctypes.wintypes.MAX_PATH)
    ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf)  # 5 = CSIDL_PERSONAL
    return Path(buf.value)


save_dir      = get_documents_folder() / "SpoTracker"
save_dir.mkdir(parents=True, exist_ok=True)

csv_file      = save_dir / "music-list.csv"
output_folder = save_dir / "reports"

MIN_LISTEN_SECONDS = 20   # minimum seconds to count as a valid play
LOW_PERC_THRESHOLD = 25   # percentage threshold for the "Low %" filter

data = []


# ── Helpers ───────────────────────────────────────────────────────────────────
def msgbox(title: str, message: str, icon: int = 0x40):
    """Show a native Windows MessageBox (no external dependencies)."""
    ctypes.windll.user32.MessageBoxW(0, message, title, icon)


def resource_path(relative: str) -> Path:
    """Resolve the path to a bundled resource.

    Works both in development (reads next to the script) and in
    PyInstaller --onefile executables (reads from sys._MEIPASS).
    """
    if hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative
    return Path(__file__).parent / relative


# ── Data model ────────────────────────────────────────────────────────────────
class TrackEntry:
    def __init__(self, artist, track, seconds_listened, date, time):
        self.artist           = artist
        self.track            = track
        self.seconds_listened = int(seconds_listened)
        self.date             = date
        self.time             = time


def load_data():
    if not csv_file.exists():
        msgbox(
            "SpoTracker — Warning",
            "No recorded tracks yet.\n\n"
            "Listen to some music on Spotify and try again.",
            0x30,  # MB_ICONWARNING
        )
        return False

    try:
        with open(csv_file, mode="r", encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split(";")
                if len(parts) >= 5:
                    data.append(TrackEntry(*parts[:5]))
    except Exception as e:
        msgbox("SpoTracker — Warning", f"Failed to read the data file:\n{e}", 0x30)
        return False

    if not data:
        msgbox(
            "SpoTracker — Warning",
            "No recorded tracks yet.\n\n"
            "Listen to some music on Spotify and try again.",
            0x30,  # MB_ICONWARNING
        )
        return False

    return True


# ── Report: tracks by artist ──────────────────────────────────────────────────
def generate_tracks_report() -> Path:
    template_path = resource_path("templates/report.html")
    try:
        template = template_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        msgbox(
            "SpoTracker — Error",
            f"Template not found:\n{template_path}",
            0x10,
        )
        raise SystemExit(1)

    tracks_by_artist: dict = {}
    today  = datetime.today()
    window = timedelta(days=30)
    recent_map: dict = {} # keeps track of recent tracks (30 days by default)

    for entry in data:
        artist  = entry.artist
        track   = entry.track
        seconds = entry.seconds_listened
        date    = datetime.strptime(entry.date, "%d-%m-%Y")

        tracks_by_artist.setdefault(artist, {})
        if track not in tracks_by_artist[artist]:
            tracks_by_artist[artist][track] = {"plays": 0, "valid_plays": 0}
            recent_map[(artist, track)] = False

        tracks_by_artist[artist][track]["plays"] += 1
        if seconds > MIN_LISTEN_SECONDS:
            tracks_by_artist[artist][track]["valid_plays"] += 1
            if date >= today - window:
                recent_map[(artist, track)] = True

    sorted_artists = OrderedDict(
        (a, OrderedDict(sorted(t.items())))
        for a, t in sorted(tracks_by_artist.items())
    )

    tracks_list = []
    for artist, tracks in sorted_artists.items():
        for track, stats in tracks.items():
            if stats["plays"] == 0:
                continue
            perc   = round(stats["valid_plays"] / stats["plays"] * 100, 2)
            recent = recent_map.get((artist, track), False)
            tracks_list.append({
                "artist":     artist,
                "track":      track,
                "validPlays": stats["valid_plays"],
                "totalPlays": stats["plays"],
                "perc":       perc,
                "recent":     recent,
            })

    html = (
        template
        .replace("{{ tracks_json }}", json.dumps(tracks_list, ensure_ascii=False))
        .replace("{{ limiar_baixo }}", str(LOW_PERC_THRESHOLD))
    )

    out = output_folder / "tracks-by-artist.html"
    out.write_text(html, encoding="utf-8")
    return out


# ── Report: top artists ───────────────────────────────────────────────────────
def generate_top_artists() -> Path:
    template_path = resource_path("templates/top-artists.html")
    try:
        template = template_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        msgbox(
            "SpoTracker — Error",
            f"Template not found:\n{template_path}",
            0x10,
        )
        raise SystemExit(1)

    entries_list = []
    for entry in data:
        entries_list.append({
            "artist":  entry.artist,
            "track":   entry.track,
            "seconds": entry.seconds_listened,
            "date":    entry.date,
        })

    html = template.replace("{{ entries_json }}", json.dumps(entries_list, ensure_ascii=False))

    out = output_folder / "top-artists.html"
    out.write_text(html, encoding="utf-8")
    return out

# ── Report: overview dashboard ────────────────────────────────────────────────
def generate_overview() -> Path:
    template_path = resource_path("templates/overview.html")
    try:
        template = template_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        msgbox(
            "SpoTracker — Error",
            f"Template not found:\n{template_path}",
            0x10,
        )
        raise SystemExit(1)

    total_seconds = 0
    total_plays   = 0
    artist_set    = set()
    track_set     = set()

    # Aggregation maps
    track_plays: dict   = {}   # (artist, track) -> plays
    artist_agg: dict    = {}   # artist -> {plays, tracks: set, seconds}
    weekday_seconds     = [0] * 7  # Mon=0, Sun=6

    for entry in data:
        sec = entry.seconds_listened
        total_plays += 1
        total_seconds += sec
        artist_set.add(entry.artist)
        track_set.add((entry.artist, entry.track))

        # Track plays (only valid plays)
        key = (entry.artist, entry.track)
        if sec > MIN_LISTEN_SECONDS:
            track_plays[key] = track_plays.get(key, 0) + 1

        # Artist aggregation
        if entry.artist not in artist_agg:
            artist_agg[entry.artist] = {"plays": 0, "tracks": set(), "seconds": 0}
        artist_agg[entry.artist]["plays"] += 1
        artist_agg[entry.artist]["tracks"].add(entry.track)
        artist_agg[entry.artist]["seconds"] += sec

        # Weekday activity
        try:
            d = datetime.strptime(entry.date, "%d-%m-%Y")
            weekday_seconds[d.weekday()] += sec
        except ValueError:
            pass

    # Top 5 tracks by valid plays
    top_tracks = sorted(track_plays.items(), key=lambda x: x[1], reverse=True)[:5]
    top_tracks_list = [
        {"artist": k[0], "track": k[1], "plays": v}
        for k, v in top_tracks
    ]

    # Top 5 artists by plays
    top_artists = sorted(
        [
            {"artist": a, "plays": d["plays"], "tracks": len(d["tracks"]), "seconds": d["seconds"]}
            for a, d in artist_agg.items()
        ],
        key=lambda x: x["plays"],
        reverse=True,
    )[:5]

    # Weekday activity (minutes)
    day_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    weekday_activity = [
        {"day": day_names[i], "minutes": round(weekday_seconds[i] / 60)}
        for i in range(7)
    ]

    # Recent activity (last 10 entries, most recent first)
    recent_entries = data[-10:][::-1]
    recent_activity = [
        {
            "artist":  e.artist,
            "track":   e.track,
            "seconds": e.seconds_listened,
            "date":    e.date,
            "time":    e.time,
        }
        for e in recent_entries
    ]

    overview = {
        "totalMinutes":   round(total_seconds / 60),
        "totalSeconds":   total_seconds,
        "totalPlays":     total_plays,
        "distinctArtists": len(artist_set),
        "distinctTracks":  len(track_set),
        "topTracks":      top_tracks_list,
        "topArtists":     top_artists,
        "weekdayActivity": weekday_activity,
        "recentActivity":  recent_activity,
    }

    html = template.replace("{{ overview_json }}", json.dumps(overview, ensure_ascii=False))

    out = output_folder / "overview.html"
    out.write_text(html, encoding="utf-8")
    return out


# ── Entry point ───────────────────────────────────────────────────────────────
def generate_stats():
    output_folder.mkdir(parents=True, exist_ok=True)

    if not load_data():
        return

    overview_path = generate_overview()
    generate_tracks_report()
    generate_top_artists()

    msgbox(
        "SpoTracker — Report generated",
        f"Report created successfully!\n\n{overview_path}\n\nOpening in browser…",
        0x40,  # MB_ICONINFORMATION
    )
    webbrowser.open(overview_path.as_uri())


generate_stats()