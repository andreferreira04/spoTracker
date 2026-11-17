"""Import Spotify's "Extended Streaming History" (.zip of JSON files) into the music list.

Each play becomes a CSV record (artist;track;seconds;dd-mm-yyyy;HH:MM:SS, start time
in local time, like the tracker writes). Plays already in the CSV are skipped: same
title and a start time within MATCH_WINDOW of an existing record. New records are
merged into the file in chronological order and a backup is made first.

The older "Account data" export (StreamingHistory_music_*.json, with endTime /
artistName / trackName / msPlayed) is accepted too.
"""
import bisect
import heapq
import json
import os
import shutil
import zipfile
from collections import namedtuple
from datetime import datetime, timedelta, timezone

MATCH_WINDOW = timedelta(minutes=3)  # max start-time difference for "the same play"

Record = namedtuple("Record", "start artist track seconds")
ImportResult = namedtuple("ImportResult", "added duplicates ignored files")


class NotAnExportError(Exception):
    """The file is not a Spotify streaming history export."""


# ── Parsing ───────────────────────────────────────────────────────────────────
def _clean(text):
    return " ".join(str(text).replace(";", ",").split())


def normalize_title(title):
    return _clean(title).casefold()


def _to_local(utc_end, ms_played):
    """Spotify timestamps are UTC and mark the END of the play; the CSV stores the local start."""
    start = utc_end - timedelta(milliseconds=ms_played)
    return start.astimezone().replace(tzinfo=None, microsecond=0)


def parse_entry(entry):
    """Return a Record for one JSON entry, or None if it isn't a song play (podcast, 0 s, bad data)."""
    if not isinstance(entry, dict):
        return None
    try:
        if "ts" in entry:  # Extended streaming history
            track = entry.get("master_metadata_track_name")
            artist = entry.get("master_metadata_album_artist_name")
            ms = int(entry.get("ms_played") or 0)
            end = datetime.strptime(entry["ts"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        elif "endTime" in entry:  # Account data export
            track = entry.get("trackName")
            artist = entry.get("artistName")
            ms = int(entry.get("msPlayed") or 0)
            end = datetime.strptime(entry["endTime"], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        else:
            return None
    except (ValueError, TypeError):
        return None
    if not track or not artist or ms <= 0:
        return None
    track, artist = _clean(track), _clean(artist)
    if not track or not artist:
        return None
    # Skips are kept (the report counts them as skips); under 1 s counts as 1 s, like the tracker
    return Record(_to_local(end, ms), artist, track, max(1, ms // 1000))


READ_SHARE = 0.9  # part of the progress bar used by reading the files (the rest: duplicates, saving)


def _no_progress(fraction, text):
    pass


def read_zip(zip_path, progress=_no_progress):
    """Return (records, ignored entries, JSON files read) from a Spotify export .zip.

    progress(fraction, text) is called as each file is read (fraction from 0 to READ_SHARE).
    """
    try:
        zf = zipfile.ZipFile(zip_path)
    except (zipfile.BadZipFile, OSError) as e:
        raise NotAnExportError(f"Could not open the .zip file:\n{e}") from e
    records, ignored, files = [], 0, 0
    with zf:
        candidates = [i for i in zf.infolist() if not i.is_dir() and i.filename.lower().endswith(".json")]
        total_bytes = sum(i.file_size for i in candidates) or 1
        read_bytes = 0
        for n, info in enumerate(candidates, 1):
            progress(READ_SHARE * read_bytes / total_bytes, f"Reading file {n} of {len(candidates)}…")
            read_bytes += info.file_size
            try:
                entries = json.loads(zf.read(info).decode("utf-8-sig"))
            except (ValueError, UnicodeDecodeError, OSError):
                continue
            if not isinstance(entries, list) or not any(
                    isinstance(e, dict) and ("ts" in e or "endTime" in e) for e in entries[:20]):
                continue  # some other file in the export (playlists, library, …)
            files += 1
            for entry in entries:
                record = parse_entry(entry)
                if record:
                    records.append(record)
                else:
                    ignored += 1
    if not files:
        raise NotAnExportError(
            "No streaming history found in this .zip.\n\n"
            "Pick the file Spotify sent you (e.g. my_spotify_data.zip) with the "
            "Extended streaming history.")
    records.sort(key=lambda r: r.start)
    return records, ignored, files


# ── CSV ───────────────────────────────────────────────────────────────────────
def parse_csv_start(parts):
    try:
        return datetime.strptime(f"{parts[3]} {parts[4]}", "%d-%m-%Y %H:%M:%S")
    except (ValueError, IndexError):
        return None


def format_record(r):
    return f"{r.artist};{r.track};{r.seconds};{r.start:%d-%m-%Y};{r.start:%H:%M:%S}"


def find_new(records, lines):
    """Split records into (new, duplicates) against the existing CSV lines.

    A record is a duplicate when an existing line has the same (normalized) title and
    starts within MATCH_WINDOW. Each existing line matches at most one record. Titles
    are compared, not artists: the export has the album artist, the tracker the artist
    shown in the Spotify window.
    """
    by_title = {}  # title -> sorted list of start times, used ones removed
    for line in lines:
        parts = line.split(";")
        start = parse_csv_start(parts) if len(parts) >= 5 else None
        if start:
            by_title.setdefault(normalize_title(parts[1]), []).append(start)
    for starts in by_title.values():
        starts.sort()

    new, duplicates = [], 0
    for r in records:
        starts = by_title.get(normalize_title(r.track))
        if starts:
            i = bisect.bisect_left(starts, r.start)
            best = min((j for j in (i - 1, i) if 0 <= j < len(starts)),
                       key=lambda j: abs(starts[j] - r.start))
            if abs(starts[best] - r.start) <= MATCH_WINDOW:
                del starts[best]
                duplicates += 1
                continue
        new.append(r)
    return new, duplicates


def merge_lines(lines, new_records):
    """Insert the (sorted) new records among the existing lines in chronological order.

    Existing lines keep their relative order; a line without a valid date stays right
    after the line before it.
    """
    def keyed_existing():
        last = datetime.min
        for line in lines:
            parts = line.split(";")
            start = parse_csv_start(parts) if len(parts) >= 5 else None
            last = start or last
            yield last, 0, line

    keyed_new = ((r.start, 1, format_record(r)) for r in new_records)
    # On equal times existing lines come first (0 < 1)
    return [line for _, _, line in heapq.merge(keyed_existing(), keyed_new, key=lambda t: (t[0], t[1]))]


def import_history(zip_path, csv_file, backup_dir, lock, progress=_no_progress):
    """Import a Spotify export into csv_file (a backup is made first). Returns an ImportResult.

    progress(fraction, text) reports how far along it is (fraction from 0 to 1); it is
    called from the thread running the import.
    """
    records, ignored, files = read_zip(zip_path, progress)
    progress(READ_SHARE, "Checking for plays already recorded…")
    with lock:
        # Read under the lock: the tracker may be appending right now
        lines = []
        if csv_file.exists():
            with open(csv_file, encoding="utf-8") as f:
                lines = [line.rstrip("\r\n") for line in f if line.strip()]
        new, duplicates = find_new(records, lines)
        if new:
            progress(READ_SHARE + (1 - READ_SHARE) / 2, f"Saving {len(new):,} new plays…")
            if csv_file.exists():
                backup_dir.mkdir(parents=True, exist_ok=True)
                shutil.copy2(csv_file, backup_dir / f"music-list-{datetime.now():%Y%m%d-%H%M%S}.csv")
            csv_file.parent.mkdir(parents=True, exist_ok=True)
            tmp = csv_file.with_suffix(".tmp")
            with open(tmp, "w", encoding="utf-8") as f:
                f.writelines(line + "\n" for line in merge_lines(lines, new))
            os.replace(tmp, csv_file)
    progress(1.0, "Done")
    return ImportResult(len(new), duplicates, ignored, files)
