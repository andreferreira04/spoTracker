# Building & Releasing SpoTracker

## Prerequisites

- Python 3.12+
- [Inno Setup 6](https://jrsoftware.org/isinfo.php) (only to build the installer)

Set up a virtual environment:

```bash
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt
```

---

## Run from source

```bash
python music-register.py                    # tray + tracker
python music-register.py --generate-report  # build the reports and exit
python music-register.py --clear-data       # open the Clear Data window
python music-register.py --self-test        # check every module loads and query Spotify once
```

`generate-stats.vbs` still runs `get_stats.py` without a console window.

---

## Tests

```bash
python -m pytest -v -rs
```

- `tests/test_integration.py` uses the real Windows APIs (`EnumWindows` on a real window, the Documents folder).
- **Against the real Spotify** (play a song first):
  ```powershell
  $env:SPOTRACKER_LIVE=1; python -m pytest tests/test_integration.py -k live -s
  ```

Tests never touch your real data: they set `SPOTRACKER_DATA_DIR` to a temporary folder and `SPOTRACKER_HEADLESS=1`, which prints dialogs instead of showing them and skips opening the browser. Both variables also work when you run the app by hand.

---

## Build Locally

### 1. Compile

```bash
pyinstaller music-register.spec --noconfirm
```

Output: `dist/SpoTracker/SpoTracker.exe` (+ `_internal/`)

### 2. Smoke test

```bash
python smoke_test.py              # add --skip-tray when there is no desktop session
```

This checks that the built app loads all its modules, generates reports, keeps a single instance and starts the tray. It uses a temporary data folder.

### 3. Build the installer

```bash
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" SpoTracker.iss
```

Output: `output/SpoTrackerInstaller.exe`

Local builds keep version `0.0.0` (in `version.py` and `SpoTracker.iss`), so the installer, tray icon, dialogs and reports are all labelled **SpoTracker (Dev)**. Only the CI workflow sets a real version.

---

## CI (`.github/workflows/main.yml`)

- **Every push to `main` and every pull request:** runs the tests.
- **Version tags (`v*`):** also builds and smoke-tests the app, builds the installer and publishes a GitHub Release with `SpoTrackerInstaller.exe`.

## Release

```bash
git add -A
git commit -m "description of changes"
git tag v1.2.0
git push origin main v1.2.0
```

Use [Semantic Versioning](https://semver.org/):
- **Major** (`v2.0.0`): breaking changes
- **Minor** (`v1.1.0`): new features
- **Patch** (`v1.0.1`): bug fixes

The release will appear at `https://github.com/<user>/<repo>/releases`.

---

## Project Structure

| File | Description |
|------|-------------|
| `music-register.py` | Entry point: tray icon, tracking thread, command-line flags |
| `platform_utils.py` | Everything OS-specific: reading Spotify, Documents folder, dialogs, file locks |
| `tracker.py` | Listening logic (pauses, ads, song changes) and CSV writing |
| `get_stats.py` | Report generator (bundled into the app, also runnable standalone) |
| `clear_data.py` | Clear Data window |
| `music-register.spec` | PyInstaller config |
| `smoke_test.py` | Checks a built app |
| `tests/` | pytest suite |
| `templates/*.html`, `templates/logo.png` | Report templates |
| `SpoTracker.iss` | Windows installer (Inno Setup) |
| `generate-stats.vbs` | Wrapper to run `get_stats.py` without a console |
