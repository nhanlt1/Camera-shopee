# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller — bản portable Windows (thư mục dist/PackRecorder/).
Chạy: pip install pyinstaller && pyinstaller packrecorder.spec
Hoặc: scripts\\build_portable.bat
"""
from pathlib import Path

import numpy as _np
from PyInstaller.utils.hooks import (
    collect_all,
    collect_delvewheel_libs_directory,
    collect_dynamic_libs,
)

project_root = Path(SPECPATH)
src = project_root / "src"

block_cipher = None

ps_datas, ps_binaries, ps_hiddenimports = collect_all("PySide6")
sh_datas, sh_binaries, sh_hiddenimports = collect_all("shiboken6")

datas = list(ps_datas) + list(sh_datas)
binaries = list(ps_binaries) + list(sh_binaries)
hiddenimports = list(ps_hiddenimports) + list(sh_hiddenimports)
extra_datas = [
    (
        str(src / "packrecorder" / "ui" / "styles.qss"),
        "packrecorder/ui",
    ),
]
_ffmpeg_dir = project_root / "resources" / "ffmpeg"
ffmpeg_exe = _ffmpeg_dir / "ffmpeg.exe"
if ffmpeg_exe.is_file():
    extra_datas.append((str(ffmpeg_exe), "."))
else:
    _picked = None
    if _ffmpeg_dir.is_dir():
        for _sub in sorted(_ffmpeg_dir.iterdir(), key=lambda p: p.name, reverse=True):
            if _sub.is_dir():
                _cand = _sub / "bin" / "ffmpeg.exe"
                if _cand.is_file():
                    _picked = _cand
                    break
    if _picked is not None:
        extra_datas.append((str(_picked), "."))

_np_exceptions = Path(_np.__file__).resolve().parent / "_core" / "_exceptions.py"
if _np_exceptions.is_file():
    extra_datas.append((str(_np_exceptions), "numpy/_core"))

for pkg in ("pyzbar", "cv2", "hidapi"):
    try:
        binaries += collect_dynamic_libs(pkg)
    except Exception:
        pass

datas, binaries = collect_delvewheel_libs_directory(
    "numpy", datas=datas, binaries=binaries
)

hiddenimports += [
    "PySide6.QtMultimedia",
    "numpy",
    "numpy._core._exceptions",
    "PIL",
    "PIL._imaging",
    "PIL.Image",
    "pyzbar",
    "pyzbar.pyzbar",
    "serial",
    "hid",
    "hidapi",
    "packrecorder.barcode_decode",
    "packrecorder.hid_scanner_discovery",
    "packrecorder.hid_pos_scan_worker",
    "packrecorder.hid_report_parse",
    "packrecorder.ipc",
    "packrecorder.ipc.capture_worker",
    "packrecorder.ipc.scanner_worker",
    "packrecorder.ipc.pipeline",
    "packrecorder.ipc.frame_ring",
    "packrecorder.ipc.encode_writer_worker",
    "packrecorder.ipc.subprocess_recorder",
    "packrecorder.storage_resolver",
    "packrecorder.recording_index",
    "packrecorder.status_publish",
    "packrecorder.sync_worker",
    "packrecorder.heartbeat_consumer",
    "packrecorder.ui.recording_search_dialog",
]

a = Analysis(
    [str(src / "packrecorder" / "__main__.py")],
    pathex=[str(src)],
    binaries=binaries,
    datas=extra_datas + datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pandas", "scipy"],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PackRecorder",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
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
    name="PackRecorder",
)
