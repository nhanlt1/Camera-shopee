"""Phát hiện chỉ số camera OpenCV thực sự mở được (tránh liệt kê 0–9 giả)."""

from __future__ import annotations

from typing import List, Optional, Set

from packrecorder.opencv_video import (
    configure_opencv_logging,
    open_video_capture,
    safe_video_capture_read,
)

configure_opencv_logging()


def probe_opencv_camera_indices(
    *,
    max_index: int = 6,
    require_frame: bool = False,
    skip_open_for_indices: Optional[Set[int]] = None,
) -> List[int]:
    """
    Thử mở từng index camera.

    skip_open_for_indices: không mở (đang bận bởi worker) — vẫn đưa index vào danh sách.
    Mặc định require_frame=False: chỉ cần isOpened() — tránh treo lâu ở read() trên Windows.
    """
    skip = skip_open_for_indices or set()
    found: list[int] = []
    configure_opencv_logging()
    for i in range(max_index + 1):
        if i in skip:
            found.append(i)
            continue
        cap = open_video_capture(i)
        try:
            if not cap.isOpened():
                continue
            if require_frame:
                ok, _ = safe_video_capture_read(cap)
                if not ok:
                    continue
            found.append(i)
        finally:
            cap.release()
    return sorted(set(found))
