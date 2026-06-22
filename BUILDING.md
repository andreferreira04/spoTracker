# Building & Releasing SpoTracker

## Prerequisites

- Python 3.12+
- [Inno Setup 6](https://jrsoftware.org/isinfo.php) installed
- Virtual environment set up:

```bash
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

---

## Build Locally

### 1. Compile the executables

```bash
# SpoTracker (tracker + system tray) — onedir build
pyinstaller music-register.spec --noconfirm

# SpoTracker-Stats (report generator) — onefile build
pyinstaller get-stats.spec --noconfirm
```

Output:
- `dist/SpoTracker/SpoTracker.exe` (+ `_internal/`)
- `dist/SpoTracker-Stats.exe`

### 2. Build the installer

```bash
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" SpoTracker.iss
```

Output:
- `output/SpoTrackerInstaller.exe`

### 3. Test without installing

Copy `dist/SpoTracker-Stats.exe` into `dist/SpoTracker/` and run `SpoTracker.exe` from that folder.

---

## Release via GitHub Actions

The CI workflow (`.github/workflows/main.yml`) builds the installer automatically when a version tag is pushed.

### 1. Commit your changes

```bash
git add -A
git commit -m "description of changes"
```

### 2. Create a version tag

```bash
git tag v1.2.0
```

Use [Semantic Versioning](https://semver.org/):
- **Major** (`v2.0.0`) — breaking changes
- **Minor** (`v1.1.0`) — new features
- **Patch** (`v1.0.1`) — bug fixes

### 3. Push with the tag

```bash
git push origin main --tags
```

This triggers the workflow which:
1. Compiles `SpoTracker.exe` and `SpoTracker-Stats.exe`
2. Builds the installer with Inno Setup
3. Creates a GitHub Release with `SpoTrackerInstaller.exe` attached

The release will appear at: `https://github.com/<user>/<repo>/releases`

---

## Project Structure

| File | Description |
|------|-------------|
| `music-register.py` | Main tracker + system tray icon |
| `music-register.spec` | PyInstaller config for the tracker |
| `get-stats.py` | Report generator |
| `get-stats.spec` | PyInstaller config for the report generator |
| `templates/report.html` | Tracks report template |
| `templates/top-artists.html` | Top artists report template |
| `SpoTracker.iss` | Inno Setup installer script |
