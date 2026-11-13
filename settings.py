"""User settings, stored as settings.json in the data folder.

Missing or invalid values fall back to their default, so a hand-edited or old
file never breaks the app. Writes go through update(), which re-reads the file
and only changes the given keys: the tray (tracking on/off) and the Settings
window (another process) can both write without overwriting each other.
"""
import json
import os

import platform_utils as pu

# name: (default, min, max) for numbers; (default,) for booleans
SPEC = {
    # Reports
    "min_listen_seconds":  (20, 0, 600),     # a play shorter than this is a skip
    "low_perc_threshold":  (25, 0, 100),     # "Low %" filter and red colour in Tracks
    "high_perc_threshold": (75, 0, 100),     # green colour in Tracks
    "recent_days":         (30, 1, 365),     # "Recent" in Tracks and the listening heatmap
    "forgotten_days":      (60, 1, 3650),    # Playlists: "Forgotten favourites" not played for this long...
    "forgotten_min_plays": (5, 1, 1000),     # ...with at least this many plays
    # App
    "check_for_updates":       (True,),
    "remember_tracking_state": (False,),     # start with tracking off if it was off when the app closed
    "tracking_enabled":        (True,),      # last on/off state from the tray (not shown in the window)
}
DEFAULTS = {name: spec[0] for name, spec in SPEC.items()}


def settings_file():
    return pu.get_data_dir() / "settings.json"


def validate(values):
    """Return a complete, valid settings dict built from values (unknown keys are dropped)."""
    result = dict(DEFAULTS)
    for name, spec in SPEC.items():
        if name not in values:
            continue
        value = values[name]
        if isinstance(spec[0], bool):
            if isinstance(value, bool):
                result[name] = value
        elif isinstance(value, int) and not isinstance(value, bool):
            result[name] = min(max(value, spec[1]), spec[2])
    if result["high_perc_threshold"] < result["low_perc_threshold"]:
        result["high_perc_threshold"] = result["low_perc_threshold"]
    return result


def load():
    try:
        values = json.loads(settings_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        values = {}
    return validate(values if isinstance(values, dict) else {})


def update(**changes):
    """Change the given settings, keep the rest as they are on disk. Returns the new settings."""
    unknown = set(changes) - set(SPEC)
    if unknown:
        raise KeyError(f"Unknown settings: {', '.join(sorted(unknown))}")
    path = settings_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    with pu.FileLock(path.with_suffix(".lock")):
        values = validate({**load(), **changes})
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(values, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    return values
