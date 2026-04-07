"""Tìm binary ffmpeg: cấu hình → kèm app (PyInstaller) → PATH → đường dẫn thường gặp."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from packrecorder.config import AppConfig

_RESOURCES_FFMPEG_SUBDIR_BIN = "bin"
_RESOURCES_FFMPEG_EXE = "ffmpeg.exe"

_FFMPEG_NOT_FOUND = (
    "Không tìm thấy ffmpeg. Thêm vào PATH hoặc chỉ đường dẫn tới ffmpeg.exe trong Cài đặt."
)


def _windows_extra_candidates() -> list[Path]:
    if os.name != "nt":
        return []
    home = Path.home()
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pfx86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    local = os.environ.get("LOCALAPPDATA", "")
    out: list[Path] = [
        Path(r"C:\ProgramData\chocolatey\bin\ffmpeg.exe"),
        home / "scoop" / "shims" / "ffmpeg.exe",
        home / "scoop" / "apps" / "ffmpeg" / "current" / "bin" / "ffmpeg.exe",
        Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
        Path(pf) / "ffmpeg" / "bin" / "ffmpeg.exe",
        Path(pfx86) / "ffmpeg" / "bin" / "ffmpeg.exe",
    ]
    if local:
        out.append(Path(local) / "Microsoft" / "WinGet" / "Links" / "ffmpeg.exe")
    return out


def pick_ffmpeg_in_resources_folder(resources_ffmpeg: Path) -> Path | None:
    """
    Tìm ffmpeg trong thư mục resources/ffmpeg của repo:
    - resources/ffmpeg/ffmpeg.exe, hoặc
    - resources/ffmpeg/<bản giải nén gyan>/bin/ffmpeg.exe (ưu tiên tên thư mục mới nhất theo sort ngược).
    """
    if not resources_ffmpeg.is_dir():
        return None
    direct = resources_ffmpeg / _RESOURCES_FFMPEG_EXE
    if direct.is_file():
        return direct.resolve()
    for sub in sorted(resources_ffmpeg.iterdir(), key=lambda p: p.name, reverse=True):
        if not sub.is_dir():
            continue
        nested = sub / _RESOURCES_FFMPEG_SUBDIR_BIN / _RESOURCES_FFMPEG_EXE
        if nested.is_file():
            return nested.resolve()
    return None


def _dev_resources_ffmpeg() -> Path | None:
    """Chạy từ source: dùng ffmpeg đi kèm repo (không áp dụng khi frozen/PyInstaller)."""
    if getattr(sys, "frozen", False):
        return None
    root = Path(__file__).resolve().parents[2]
    return pick_ffmpeg_in_resources_folder(root / "resources" / "ffmpeg")


def _bundled_ffmpeg() -> Path | None:
    """PyInstaller onedir: ffmpeg.exe cạnh .exe; onefile: trong _MEIPASS."""
    if not getattr(sys, "frozen", False):
        return None
    exe_dir = Path(sys.executable).resolve().parent
    for name in ("ffmpeg.exe", "ffmpeg"):
        p = exe_dir / name
        if p.is_file():
            return p.resolve()
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        base = Path(meipass)
        for name in ("ffmpeg.exe", "ffmpeg"):
            p = base / name
            if p.is_file():
                return p.resolve()
    return None


def resolve_ffmpeg(cfg: AppConfig) -> Path:
    """Trả về đường dẫn tuyệt đối tới ffmpeg nếu tìm được."""
    raw = (cfg.ffmpeg_path or "").strip().strip('"')
    if raw:
        p = Path(raw)
        if p.is_file():
            return p.resolve()
    bundled = _bundled_ffmpeg()
    if bundled is not None:
        return bundled
    dev_local = _dev_resources_ffmpeg()
    if dev_local is not None:
        return dev_local
    w = shutil.which("ffmpeg")
    if w:
        return Path(w).resolve()
    for c in _windows_extra_candidates():
        try:
            if c.is_file():
                return c.resolve()
        except OSError:
            continue
    raise FileNotFoundError(_FFMPEG_NOT_FOUND)
