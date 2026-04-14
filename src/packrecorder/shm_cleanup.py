"""Dọn SharedMemory POSIX orphan (tên packrecorder_pr_*). Windows: không liệt kê an toàn — no-op."""

from __future__ import annotations

import sys
from pathlib import Path

import multiprocessing.shared_memory as sm

from packrecorder.ipc.frame_ring import SHM_NAME_PREFIX


def cleanup_stale_packrecorder_shm() -> int:
    """
    Thử unlink các segment shm còn sót tên `packrecorder_pr_*` trong /dev/shm.
    Chỉ chạy trên POSIX; Windows trả 0 (shm đặt tên vẫn unlink trong close_unlink khi thoát đúng).
    """
    if sys.platform == "win32":
        return 0
    cleaned = 0
    root = Path("/dev/shm")
    if not root.is_dir():
        return 0
    pattern = f"{SHM_NAME_PREFIX}*"
    for p in root.glob(pattern):
        if not p.is_file():
            continue
        name = p.name
        try:
            mem = sm.SharedMemory(name=name)
            try:
                mem.close()
            except BufferError:
                pass
            try:
                mem.unlink()
            except FileNotFoundError:
                pass
            cleaned += 1
        except Exception:
            continue
    return cleaned
