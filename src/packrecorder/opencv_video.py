"""Mở VideoCapture ổn định trên Windows (MSMF trước, tránh lỗi DSHOW + index)."""

from __future__ import annotations

import os
import sys

# Phải đặt trước `import cv2` để giảm log C++ (FFmpeg/DShow) lúc nạp module.
os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")

import cv2


def configure_opencv_logging() -> None:
    """Tắt/giảm log OpenCV (obsensor, dshow, ffmpeg) khi thử nhiều backend/index."""
    try:
        log = cv2.utils.logging
        silent = getattr(log, "LOG_LEVEL_SILENT", None)
        if silent is not None:
            log.setLogLevel(silent)
        else:
            log.setLogLevel(log.LOG_LEVEL_ERROR)
    except Exception:
        pass


configure_opencv_logging()


def open_video_capture(index: int) -> cv2.VideoCapture:
    """
    Windows: thử Media Foundation (MSMF) trước — nhiều bản OpenCV không cho DSHOW + index.
    Fallback: backend mặc định, cuối cùng mới DirectShow.
    """
    if sys.platform != "win32":
        return cv2.VideoCapture(index)

    order: list[int] = []
    cap_msmf = getattr(cv2, "CAP_MSMF", None)
    if cap_msmf is not None:
        order.append(int(cap_msmf))
    order.append(0)
    cap_dshow = getattr(cv2, "CAP_DSHOW", None)
    if cap_dshow is not None:
        order.append(int(cap_dshow))

    last: cv2.VideoCapture | None = None
    for api in order:
        cap = cv2.VideoCapture(index, api)
        last = cap
        if cap.isOpened():
            return cap
        cap.release()
    return last if last is not None else cv2.VideoCapture(index)
