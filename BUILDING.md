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

### 1. Compile the executable

```bash
pyinstaller music-register.spec --noconfirm
```

Output:
- `dist/SpoTracker/SpoTracker.exe` (+ `_internal/`)

### 2. Build the installer

```bash
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" SpoTracker.iss
```

Output:
- `output/SpoTrackerInstaller.exe`

### 3. Test before releasing

```bash
.\smoke-test.ps1
```

This verifies the executable starts correctly and can generate reports without missing modules.

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
git push origin main v1.2.0
```

This triggers the workflow which:
1. Compiles `SpoTracker.exe`
2. Builds the installer with Inno Setup
3. Creates a GitHub Release with `SpoTrackerInstaller.exe` attached

The release will appear at: `https://github.com/<user>/<repo>/releases`

---

## Project Structure

| File | Description |
|------|-------------|
| `music-register.py` | Main tracker + system tray icon |
| `music-register.spec` | PyInstaller config (builds everything) |
| `get-stats.py` | Report generator (bundled into the exe, also runnable standalone) |
| `generate-stats.vbs` | Standalone wrapper to run `get-stats.py` without the exe |
| `templates/*.html` | Report HTML templates |
| `SpoTracker.iss` | Inno Setup installer script |
