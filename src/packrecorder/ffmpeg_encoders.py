"""Kiểm tra encoder FFmpeg (libx265 / libx264) có sẵn — có cache theo đường dẫn exe."""

from __future__ import annotations

import subprocess
from pathlib import Path
from threading import Lock

from packrecorder.subprocess_win import run_extra_kwargs

_cache: dict[tuple[str, str], bool] = {}
_lock = Lock()


def ffmpeg_lists_encoder(ffmpeg_exe: Path, encoder_substr: str) -> bool:
    """
    True nếu `ffmpeg -encoders` có chứa chuỗi (vd. "libx265").
    Dùng để ưu tiên HEVC khi build FFmpeg có libx265.
    """
    key = (str(ffmpeg_exe.resolve()), encoder_substr)
    with _lock:
        if key in _cache:
            return _cache[key]
        ok = False
        try:
            r = subprocess.run(
                [str(ffmpeg_exe), "-hide_banner", "-encoders"],
                capture_output=True,
                timeout=20,
                text=True,
                encoding="utf-8",
                errors="replace",
                **run_extra_kwargs(),
            )
            text = (r.stdout or "") + (r.stderr or "")
            ok = r.returncode == 0 and encoder_substr in text
        except Exception:
            ok = False
        _cache[key] = ok
        return ok
