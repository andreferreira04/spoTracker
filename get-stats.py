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


# ── Embedded artists-per-day template ────────────────────────────────────────
APD_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Artists per Day</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap" rel="stylesheet">
  <style>
    :root{{--card:#111827;--border:#1f2933;--text:#e5e7eb;--muted:#9ca3af}}
    *{{box-sizing:border-box;margin:0;padding:0}}
    body{{font-family:"Inter",sans-serif;background:linear-gradient(135deg,#020617,#0f172a);color:var(--text);display:flex;justify-content:center;padding:40px 16px}}
    .container{{width:100%;max-width:800px}}
    h1{{text-align:center;font-weight:700;margin-bottom:28px;background:linear-gradient(90deg,#60a5fa,#a78bfa);-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text}}
    .card{{background:var(--card);border-radius:16px;padding:18px;box-shadow:0 10px 25px rgba(0,0,0,.35);border:1px solid var(--border)}}
    table{{width:100%;border-collapse:collapse}}
    th{{text-align:left;font-weight:500;color:var(--muted);font-size:.85rem;padding:12px;border-bottom:1px solid var(--border)}}
    td{{padding:12px;border-bottom:1px solid var(--border);font-size:.9rem}}
    tr:last-child td{{border-bottom:none}}
    tbody tr:hover{{background:rgba(59,130,246,.05)}}
  </style>
</head>
<body>
  <div class="container">
    <h1>Artists per Day (last 30 days)</h1>
    <div class="card">
      {content}
    </div>
  </div>
</body>
</html>"""


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
            "SpoTracker — Error",
            f"Data file not found:\n{csv_file}\n\n"
            "Make sure SpoTracker has already recorded some tracks.",
            0x10,  # MB_ICONERROR
        )
        raise SystemExit(1)

    try:
        with open(csv_file, mode="r", encoding="utf-8") as f:
            for line in f:
                parts = line.rstrip("\n").split(";")
                if len(parts) >= 5:
                    data.append(TrackEntry(*parts[:5]))
    except Exception as e:
        msgbox("SpoTracker — Error", f"Failed to read the data file:\n{e}", 0x10)
        raise SystemExit(1)


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


# ── Report: artists per day ───────────────────────────────────────────────────
def generate_artists_per_day():
    artists_per_day: dict = {}
    today  = datetime.today()
    window = timedelta(days=30)

    for entry in data:
        entry_date = datetime.strptime(entry.date, "%d-%m-%Y")
        if entry_date >= today - window and entry.seconds_listened >= MIN_LISTEN_SECONDS:
            artists_per_day.setdefault(entry.date, {})
            artists_per_day[entry.date][entry.artist] = (
                artists_per_day[entry.date].get(entry.artist, 0) + 1
            )

    sorted_days = OrderedDict(sorted(artists_per_day.items()))

    rows_html = ""
    for date, artists in sorted_days.items():
        top3 = sorted(artists.items(), key=lambda x: x[1], reverse=True)[:3]
        top_artists = "<br>".join(f"{a} ({n}x)" for a, n in top3)
        rows_html += f"<tr><td>{date}</td><td>{top_artists}</td></tr>"

    content = (
        "<table><thead><tr><th>Date</th><th>Top 3 Artists</th></tr></thead>"
        f"<tbody>{rows_html}</tbody></table>"
    )
    html = APD_TEMPLATE.format(content=content)

    out = output_folder / "artists-per-day.html"
    out.write_text(html, encoding="utf-8")
    return out


# ── Entry point ───────────────────────────────────────────────────────────────
def generate_stats():
    output_folder.mkdir(parents=True, exist_ok=True)

    load_data()

    report_path = generate_tracks_report()
    generate_artists_per_day()
    generate_top_artists()

    msgbox(
        "SpoTracker — Report generated",
        f"Report created successfully!\n\n{report_path}\n\nOpening in browser…",
        0x40,  # MB_ICONINFORMATION
    )
    webbrowser.open(report_path.as_uri())


generate_stats()