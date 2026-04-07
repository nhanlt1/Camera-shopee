# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller — bản portable Windows (thư mục dist/PackRecorder/).
Chạy: pip install pyinstaller && pyinstaller packrecorder.spec
Hoặc: scripts\\build_portable.bat
"""
from pathlib import Path

from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs

project_root = Path(SPECPATH)
src = project_root / "src"

block_cipher = None

ps_datas, ps_binaries, ps_hiddenimports = collect_all("PySide6")

datas = [
    (
        str(src / "packrecorder" / "ui" / "styles.qss"),
        "packrecorder/ui",
    ),
]
_ffmpeg_dir = project_root / "resources" / "ffmpeg"
ffmpeg_exe = _ffmpeg_dir / "ffmpeg.exe"
if ffmpeg_exe.is_file():
    datas.append((str(ffmpeg_exe), "."))
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
        datas.append((str(_picked), "."))

binaries = list(ps_binaries)
for pkg in ("pyzbar", "cv2"):
    try:
        binaries += collect_dynamic_libs(pkg)
    except Exception:
        pass

hiddenimports = list(ps_hiddenimports) + [
    "PySide6.QtMultimedia",
    "numpy",
    "PIL",
    "PIL._imaging",
    "PIL.Image",
    "pyzbar",
    "pyzbar.pyzbar",
    "serial",
]

a = Analysis(
    [str(src / "packrecorder" / "__main__.py")],
    pathex=[str(src)],
    binaries=binaries,
    datas=datas + ps_datas,
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
