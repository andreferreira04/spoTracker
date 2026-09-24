"""Clear Data dialog: remove recorded plays from the music list (a backup is made first)."""
import os
import shutil
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

from version import APP_NAME

ALL_TRACKS = "(all tracks)"

_dialog_open = False


# ── Data helpers ──────────────────────────────────────────────────────────────
def read_lines(csv_file):
    if not csv_file.exists():
        return []
    with open(csv_file, encoding="utf-8") as f:
        return [line.rstrip("\n") for line in f if line.strip()]


def matches(line, predicate):
    parts = line.split(";")
    return len(parts) >= 5 and predicate(parts)


def line_size(line) -> int:
    """Bytes a record takes on disk (text mode writes os.linesep, e.g. \\r\\n on Windows)."""
    return len(line.encode("utf-8")) + len(os.linesep)


def format_size(size) -> str:
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.2f} MB"


def remove_records(csv_file, backup_dir, lock, predicate) -> int:
    """Remove the records matching predicate, after backing up the file. Returns how many were removed."""
    with lock:
        # Re-read under the lock: the tracker may have saved new plays since the dialog opened
        lines = read_lines(csv_file)
        keep = [line for line in lines if not matches(line, predicate)]
        removed = len(lines) - len(keep)
        if removed == 0:
            return 0

        backup_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(csv_file, backup_dir / f"music-list-{datetime.now():%Y%m%d-%H%M%S}.csv")

        tmp = csv_file.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(line + "\n" for line in keep)
        os.replace(tmp, csv_file)
    return removed


# ── Dialog ────────────────────────────────────────────────────────────────────
def open_dialog(csv_file, backup_dir, lock):
    """Show the Clear Data window (blocking; run it in its own thread)."""
    global _dialog_open
    if _dialog_open:
        return
    _dialog_open = True
    try:
        _run_dialog(csv_file, backup_dir, lock)
    finally:
        _dialog_open = False


def _run_dialog(csv_file, backup_dir, lock):
    lines = read_lines(csv_file)
    total_size = csv_file.stat().st_size if csv_file.exists() else 0
    tracks_by_artist = {}
    for line in lines:
        parts = line.split(";")
        if len(parts) >= 5:
            tracks_by_artist.setdefault(parts[0], set()).add(parts[1])
    artists = sorted(tracks_by_artist, key=str.casefold)
    artists_by_folded = {a.casefold(): a for a in artists}

    root = tk.Tk()
    root.title(f"{APP_NAME} — Clear Data")
    root.resizable(False, False)
    root.attributes("-topmost", True)

    frm = ttk.Frame(root, padding=16)
    frm.grid()

    mode       = tk.StringVar(value="before")
    date_var   = tk.StringVar(value=datetime.today().strftime("%d-%m-%Y"))
    artist_var = tk.StringVar()
    track_var  = tk.StringVar(value=ALL_TRACKS)
    preview    = tk.StringVar()

    ttk.Label(frm, text="Choose which records to remove:").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

    # Before a date
    ttk.Radiobutton(frm, text="Records before", variable=mode, value="before").grid(row=1, column=0, sticky="w", pady=4)
    date_entry = ttk.Entry(frm, textvariable=date_var, width=14)
    date_entry.grid(row=1, column=1, sticky="w", padx=(8, 0))
    ttk.Label(frm, text="dd-mm-yyyy", foreground="gray").grid(row=1, column=2, sticky="w", padx=(8, 0))

    # Artist / track
    ttk.Radiobutton(frm, text="Artist", variable=mode, value="artist").grid(row=2, column=0, sticky="w", pady=4)
    artist_box = ttk.Combobox(frm, textvariable=artist_var, values=artists, width=40)
    artist_box.grid(row=2, column=1, columnspan=2, sticky="we", padx=(8, 0))
    ttk.Label(frm, text="Track").grid(row=3, column=0, sticky="w", padx=(22, 0), pady=4)
    track_box = ttk.Combobox(frm, textvariable=track_var, values=[ALL_TRACKS], state="readonly", width=40)
    track_box.grid(row=3, column=1, columnspan=2, sticky="we", padx=(8, 0))

    # Everything
    ttk.Radiobutton(frm, text="All data", variable=mode, value="all").grid(row=4, column=0, sticky="w", pady=4)

    ttk.Separator(frm).grid(row=5, column=0, columnspan=3, sticky="we", pady=10)
    ttk.Label(frm, textvariable=preview).grid(row=6, column=0, columnspan=3, sticky="w")
    ttk.Label(
        frm, text=f"A backup of your data is saved to {backup_dir} before removing.",
        foreground="gray", wraplength=420,
    ).grid(row=7, column=0, columnspan=3, sticky="w", pady=(4, 12))

    buttons = ttk.Frame(frm)
    buttons.grid(row=8, column=0, columnspan=3, sticky="e")
    clear_btn = ttk.Button(buttons, text="Clear")
    clear_btn.grid(row=0, column=0, padx=(0, 8))
    ttk.Button(buttons, text="Cancel", command=root.destroy).grid(row=0, column=1)

    def resolve_artist():
        name = artist_var.get().strip()
        return name if name in tracks_by_artist else artists_by_folded.get(name.casefold())

    def build_predicate():
        """Return (predicate, error message)."""
        m = mode.get()
        if m == "all":
            return (lambda p: True), None
        if m == "before":
            try:
                cutoff = datetime.strptime(date_var.get().strip(), "%d-%m-%Y")
            except ValueError:
                return None, "Invalid date — use dd-mm-yyyy."

            def before(p):
                try:
                    return datetime.strptime(p[3], "%d-%m-%Y") < cutoff
                except ValueError:
                    return False
            return before, None
        artist = resolve_artist()
        if not artist:
            return None, "Choose an artist from the list."
        track = track_var.get()
        return (lambda p: p[0] == artist and (track == ALL_TRACKS or p[1] == track)), None

    def refresh(*_):
        predicate, error = build_predicate()
        if error:
            preview.set(error)
            clear_btn.state(["disabled"])
            return
        count, saved = selection_stats(predicate)
        preview.set(
            f"{count} of {len(lines)} records will be removed.\n"
            f"Estimated space freed: {format_size(saved)} of {format_size(total_size)}."
        )
        clear_btn.state(["!disabled"] if count else ["disabled"])

    def selection_stats(predicate):
        """Return (records matched, bytes they take in the CSV)."""
        selected = [line for line in lines if matches(line, predicate)]
        return len(selected), sum(line_size(line) for line in selected)

    def on_artist_change(*_):
        artist = resolve_artist()
        tracks = sorted(tracks_by_artist.get(artist, ()), key=str.casefold)
        track_box["values"] = [ALL_TRACKS] + tracks
        if track_var.get() not in track_box["values"]:
            track_var.set(ALL_TRACKS)
        refresh()

    def filter_artists(event):
        if event.keysym in ("Up", "Down", "Return", "Escape"):
            return
        q = artist_var.get().strip().casefold()
        artist_box["values"] = [a for a in artists if q in a.casefold()] if q else artists

    def on_clear():
        predicate, _ = build_predicate()
        if predicate is None:
            return
        count, saved = selection_stats(predicate)
        if not messagebox.askyesno(
            f"{APP_NAME} — Confirm",
            f"Remove {count} records?\n"
            f"About {format_size(saved)} of {format_size(total_size)} will be freed.\n\n"
            "This can only be undone by restoring the backup.",
            icon="warning", parent=root,
        ):
            return
        try:
            removed = remove_records(csv_file, backup_dir, lock, predicate)
        except OSError as e:
            messagebox.showerror(f"{APP_NAME} — Error", f"Failed to clear data:\n{e}", parent=root)
            return
        messagebox.showinfo(
            f"{APP_NAME} — Clear Data",
            f"{removed} records removed.\n\nGenerate a new report to see the changes.",
            parent=root,
        )
        root.destroy()

    mode.trace_add("write", refresh)
    date_var.trace_add("write", refresh)
    artist_var.trace_add("write", on_artist_change)
    track_var.trace_add("write", refresh)
    date_entry.bind("<FocusIn>", lambda _: mode.set("before"))
    artist_box.bind("<FocusIn>", lambda _: mode.set("artist"))
    track_box.bind("<FocusIn>", lambda _: mode.set("artist"))
    artist_box.bind("<KeyRelease>", filter_artists)
    clear_btn.configure(command=on_clear)

    refresh()
    root.mainloop()
