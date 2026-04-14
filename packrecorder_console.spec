# -*- mode: python ; coding: utf-8 -*-
# Build: pyinstaller packrecorder_console.spec --noconfirm
# Onedir: dist/PackRecorder_console/PackRecorder_console.exe
# ffmpeg: PATH hoac PACKRECORDER_FFMPEG (giong packrecorder.spec)

import os
import shutil
from pathlib import Path

import pyzbar
from PyInstaller.utils.hooks import (
    collect_all,
    collect_delvewheel_libs_directory,
    collect_dynamic_libs,
)

block_cipher = None

datas, binaries, hiddenimports = collect_all("PySide6")
s_data, s_bin, s_hi = collect_all("shiboken6")
datas += s_data
binaries += s_bin
hiddenimports += s_hi

datas, binaries = collect_delvewheel_libs_directory("numpy", datas=datas, binaries=binaries)

for _dll in Path(pyzbar.__file__).resolve().parent.glob("*.dll"):
    binaries.append((str(_dll), "pyzbar"))

try:
    binaries += collect_dynamic_libs("hidapi")
except Exception:
    pass

project_root = Path(SPECPATH)
_ffmpeg_src = (os.environ.get("PACKRECORDER_FFMPEG") or "").strip() or shutil.which(
    "ffmpeg"
)
if not (_ffmpeg_src and Path(_ffmpeg_src).is_file()):
    _fd = project_root / "resources" / "ffmpeg"
    _flat = _fd / "ffmpeg.exe"
    if _flat.is_file():
        _ffmpeg_src = str(_flat)
    elif _fd.is_dir():
        for _sub in sorted(_fd.iterdir(), key=lambda p: p.name, reverse=True):
            if _sub.is_dir():
                _cand = _sub / "bin" / "ffmpeg.exe"
                if _cand.is_file():
                    _ffmpeg_src = str(_cand)
                    break
if _ffmpeg_src and Path(_ffmpeg_src).is_file():
    binaries.append((str(Path(_ffmpeg_src).resolve()), "."))
else:
    raise SystemExit(
        "PyInstaller: khong tim thay ffmpeg. Cai ffmpeg (PATH) hoac dat "
        "PACKRECORDER_FFMPEG=duong\\dan\\ffmpeg.exe roi build lai."
    )

_rth = os.path.join(SPECPATH, "packrecorder_rth_dlls.py")

a = Analysis(
    ["src/packrecorder/__main__.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports
    + [
        "hid",
        "hidapi",
        "packrecorder.hid_scanner_discovery",
        "packrecorder.hid_pos_scan_worker",
        "packrecorder.hid_report_parse",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[_rth],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PackRecorder_console",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PackRecorder_console",
)
