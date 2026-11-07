"""Turns a stream of "now playing" samples into listening records in the CSV."""
import os
from datetime import datetime


def get_last_record(f):
    """Return (offset, line) of the last line in the binary file f, or (0, b"") if empty."""
    f.seek(0, os.SEEK_END)
    pos = f.tell()
    chunk = b""
    while pos > 0:
        size = min(4096, pos)
        pos -= size
        f.seek(pos)
        chunk = f.read(size) + chunk
        idx = chunk.rstrip(b"\r\n").rfind(b"\n")
        if idx != -1:
            return pos + idx + 1, chunk[idx + 1:]
    return 0, chunk


def save_music(csv_file, lock, artist, music, seconds_listened, date, hour):
    """Append a record, or add to the last one when it is the same song."""
    try:
        music = music.replace(";", ",")
        artist = artist.replace(";", ",")
        with lock, open(csv_file, "a+b") as f:
            # Same song as the last record (e.g. Spotify closed and reopened mid-song): aggregate instead of adding a new record
            offset, last_line = get_last_record(f)
            parts = last_line.decode("utf-8").strip().split(";")
            if len(parts) >= 5 and parts[0] == artist and parts[1] == music and parts[2].isdigit():
                seconds_listened += int(parts[2])
                date, hour = parts[3], parts[4]
                f.truncate(offset)
            f.write(f"{artist};{music};{seconds_listened};{date};{hour}{os.linesep}".encode("utf-8"))
    except Exception:
        print("Error saving music in file", csv_file)


class Tracker:
    """Feed it one NowPlaying (or None when Spotify is closed) per tick with update().

    `save(artist, music, seconds, date, hour)` is called each time a song ends,
    with the time actually listened (pauses and ads excluded).
    """

    def __init__(self, save):
        self.save = save
        self._reset()

    def _reset(self):
        self.artist = ""
        self.music = ""
        self.date = None
        self.hour = None
        self.music_start = None
        self.total_pause = 0.0
        self.pause_start = None     # timestamp when the pause began (None = not paused)

    def _listened(self, now):
        pause = self.total_pause
        if self.pause_start is not None:
            pause += now - self.pause_start
        return int(now - self.music_start - pause)

    def _flush(self, now):
        """Save the current song, if any."""
        if self.music_start is not None and self.artist and self.music:
            seconds = self._listened(now)
            if seconds > 0:
                self.save(self.artist, self.music, seconds, self.date, self.hour)

    def update(self, state, now, today=None):
        """Process one sample. Returns True when a new song started."""
        # Spotify not running: save the song that was playing before it closed
        if state is None:
            self._flush(now)
            self._reset()
            return False

        # Paused / ads
        if not state.playing:
            if self.pause_start is None:
                self.pause_start = now
            return False

        # Playing
        if self.pause_start is not None:
            self.total_pause += now - self.pause_start
            self.pause_start = None

        if state.artist == self.artist and state.title == self.music:
            return False

        # Song changed
        self._flush(now)
        today = today or datetime.today()
        self.artist = state.artist
        self.music = state.title
        self.date = today.strftime("%d-%m-%Y")
        self.hour = today.strftime("%H:%M:%S")
        self.music_start = now
        self.total_pause = 0.0
        return True

    def stop(self, now):
        """Save the current song (e.g. when the app quits)."""
        self._flush(now)
        self._reset()
