# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    ['get-stats.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('templates/report.html', 'templates'),  # bundled into the exe
        ('templates/top-artists.html', 'templates'),
        ('templates/overview.html', 'templates'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)

# One-file executable — all dependencies bundled into a single .exe
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SpoTracker-Stats',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # no console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
