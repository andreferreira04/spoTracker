"""Settings window, opened from the tray in its own process (like Clear Data)."""
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

import platform_utils as pu
import settings
from version import APP_NAME

# (setting, label, unit) grouped by section; numbers get a spinbox, booleans a checkbox
SECTIONS = [
    ("Reports", [
        ("min_listen_seconds",  "Minimum listening time to count as a play", "seconds"),
        ("low_perc_threshold",  "\"Low %\" threshold in Tracks",             "%"),
        ("high_perc_threshold", "\"High %\" threshold in Tracks",            "%"),
        ("recent_days",         "\"Recent\" period and listening heatmap",   "days"),
        ("forgotten_days",      "Forgotten favourites: not played for",      "days"),
        ("forgotten_min_plays", "Forgotten favourites: at least",            "plays"),
    ]),
    ("App", [
        ("check_for_updates",       "Check for updates when SpoTracker starts", None),
        ("remember_tracking_state", "Remember if tracking was turned off when SpoTracker closes", None),
    ]),
]
REPORT_SETTINGS = [name for name, _, _ in SECTIONS[0][1]]


def parse_form(raw):
    """Turn the window's text values into settings. Returns (values, error message)."""
    values = {}
    for name, value in raw.items():
        default, *limits = settings.SPEC[name]
        if isinstance(default, bool):
            values[name] = bool(value)
            continue
        low, high = limits
        try:
            number = int(str(value).strip())
        except ValueError:
            return None, f"Enter a whole number for \"{label_of(name)}\"."
        if not low <= number <= high:
            return None, f"\"{label_of(name)}\" must be between {low} and {high}."
        values[name] = number
    if values.get("high_perc_threshold", 100) < values.get("low_perc_threshold", 0):
        return None, "The \"High %\" threshold can't be lower than the \"Low %\" threshold."
    return values, None


def label_of(name):
    return next(label for _, rows in SECTIONS for n, label, _ in rows if n == name)


def open_dialog(dialog_lock, regenerate, import_history=None):
    """Show the Settings window (blocking). dialog_lock keeps a single window open;
    regenerate() is called when the user asks to rebuild the report after a change.
    import_history(zip_path) imports a Spotify export and returns a spotify_import.ImportResult."""
    if not dialog_lock.acquire(blocking=False):
        return
    try:
        _run_dialog(regenerate, import_history)
    finally:
        dialog_lock.release()


def import_summary(result):
    """Text shown after an import."""
    lines = [f"{result.added:,} plays added from {result.files} file{'s' if result.files != 1 else ''}."]
    if result.duplicates:
        lines.append(f"{result.duplicates:,} were already recorded and were skipped.")
    if result.ignored:
        lines.append(f"{result.ignored:,} podcasts, videos or entries with no listening time were ignored.")
    return "\n".join(lines)


def _run_dialog(regenerate, import_history=None):
    current = settings.load()

    root = tk.Tk()
    root.title(f"{APP_NAME} — Settings")
    pu.set_window_icon(root)
    root.resizable(False, False)
    root.attributes("-topmost", True)

    frm = ttk.Frame(root, padding=16)
    frm.grid()

    variables = {}
    busy = {"importing": False}  # the window can't be closed while an import runs

    def close():
        if not busy["importing"]:
            root.destroy()
    root.protocol("WM_DELETE_WINDOW", close)

    row = 0
    for section, rows in SECTIONS:
        ttk.Label(frm, text=section, font=("TkDefaultFont", 10, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(0 if row == 0 else 14, 6))
        row += 1
        for name, label, unit in rows:
            default, *limits = settings.SPEC[name]
            if isinstance(default, bool):
                var = tk.BooleanVar(value=current[name])
                ttk.Checkbutton(frm, text=label, variable=var).grid(row=row, column=0, columnspan=3, sticky="w", pady=3)
            else:
                var = tk.StringVar(value=str(current[name]))
                ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", pady=3)
                ttk.Spinbox(frm, from_=limits[0], to=limits[1], textvariable=var, width=7).grid(
                    row=row, column=1, sticky="w", padx=(12, 6))
                ttk.Label(frm, text=unit, foreground="gray").grid(row=row, column=2, sticky="w")
            variables[name] = var
            row += 1
        if section == "Reports":
            ttk.Label(
                frm, text="Report settings apply to all your history the next time the report is generated.",
                foreground="gray", wraplength=420,
            ).grid(row=row, column=0, columnspan=3, sticky="w", pady=(6, 0))
            row += 1

    if import_history:
        ttk.Label(frm, text="Spotify history", font=("TkDefaultFont", 10, "bold")).grid(
            row=row, column=0, columnspan=3, sticky="w", pady=(14, 6))
        row += 1
        ttk.Label(
            frm, wraplength=420, foreground="gray",
            text="Add your past listening from the \"Extended streaming history\" you can request "
                 "from Spotify (Account → Privacy settings).",
        ).grid(row=row, column=0, columnspan=3, sticky="w")
        row += 1
        import_btn = ttk.Button(frm, text="Import Spotify history (.zip)…")
        import_btn.grid(row=row, column=0, sticky="w", pady=(8, 0))
        row += 1
        # Progress bar + step text, shown only while importing
        import_progress = ttk.Frame(frm)
        import_progress.grid(row=row, column=0, columnspan=3, sticky="we", pady=(8, 0))
        import_progress.columnconfigure(0, weight=1)
        progress_value = tk.DoubleVar()
        progress_text = tk.StringVar()
        ttk.Progressbar(import_progress, variable=progress_value, maximum=1.0).grid(row=0, column=0, sticky="we")
        ttk.Label(import_progress, textvariable=progress_text, foreground="gray").grid(
            row=1, column=0, sticky="w", pady=(4, 0))
        import_progress.grid_remove()
        row += 1

        def run_import():
            path = filedialog.askopenfilename(
                parent=root, title="Choose your Spotify data (.zip)",
                filetypes=[("Spotify data", "*.zip"), ("All files", "*.*")])
            if not path:
                return
            busy["importing"] = True
            import_btn.state(["disabled"])
            progress_value.set(0)
            progress_text.set("Opening the file…")
            import_progress.grid()
            outcome = {"progress": (0.0, "Opening the file…")}

            def report(fraction, text):
                # Runs in the worker thread: only store it, poll() updates the window
                outcome["progress"] = (fraction, text)

            def work():
                try:
                    outcome["result"] = import_history(path, report)
                except Exception as e:  # shown to the user below
                    outcome["error"] = e

            def poll():
                fraction, text = outcome["progress"]
                progress_value.set(fraction)
                progress_text.set(text)
                if worker.is_alive():
                    root.after(150, poll)
                    return
                busy["importing"] = False
                import_btn.state(["!disabled"])
                import_progress.grid_remove()
                if "error" in outcome:
                    messagebox.showerror(f"{APP_NAME} — Import", f"Import failed:\n\n{outcome['error']}", parent=root)
                    return
                result = outcome["result"]
                if not result.added:
                    messagebox.showinfo(f"{APP_NAME} — Import", import_summary(result), parent=root)
                elif messagebox.askyesno(
                        f"{APP_NAME} — Import",
                        import_summary(result) + "\n\nGenerate a new report now?", parent=root):
                    root.destroy()
                    regenerate()

            worker = threading.Thread(target=work, daemon=True)
            worker.start()
            poll()

        import_btn.configure(command=run_import)

    error = tk.StringVar()
    ttk.Label(frm, textvariable=error, foreground="#c0392b", wraplength=420).grid(
        row=row, column=0, columnspan=3, sticky="w", pady=(6, 0))
    row += 1

    buttons = ttk.Frame(frm)
    buttons.grid(row=row, column=0, columnspan=3, sticky="we", pady=(12, 0))
    buttons.columnconfigure(0, weight=1)

    def restore_defaults():
        for name, var in variables.items():
            var.set(settings.DEFAULTS[name] if isinstance(var, tk.BooleanVar) else str(settings.DEFAULTS[name]))
        error.set("")

    def save():
        if busy["importing"]:
            return
        values, message = parse_form({name: var.get() for name, var in variables.items()})
        if message:
            error.set(message)
            return
        try:
            saved = settings.update(**values)
        except OSError as e:
            messagebox.showerror(f"{APP_NAME} — Error", f"Failed to save settings:\n{e}", parent=root)
            return
        reports_changed = any(saved[name] != current[name] for name in REPORT_SETTINGS)
        rebuild = reports_changed and messagebox.askyesno(
            f"{APP_NAME} — Settings",
            "Settings saved.\n\nGenerate a new report now to apply them?",
            parent=root,
        )
        root.destroy()
        if rebuild:
            regenerate()

    ttk.Button(buttons, text="Restore defaults", command=restore_defaults).grid(row=0, column=0, sticky="w")
    ttk.Button(buttons, text="Save", command=save).grid(row=0, column=1, padx=(0, 8))
    ttk.Button(buttons, text="Cancel", command=close).grid(row=0, column=2)

    root.bind("<Return>", lambda _: save())
    root.bind("<Escape>", lambda _: close())
    root.mainloop()
