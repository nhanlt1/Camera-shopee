"""Mở VideoCapture ổn định trên Windows (MSMF trước, tránh lỗi DSHOW + index)."""

from __future__ import annotations

import os
import sys

# Phải đặt trước `import cv2` để giảm log C++ (FFmpeg/DShow) lúc nạp module.
os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")
# Giảm độ trễ / treo khi mở webcam qua MSMF (đặt trước import cv2).
os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")

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


def _env_truthy(name: str) -> bool:
    v = os.environ.get(name, "").strip().lower()
    return v in ("1", "true", "yes", "on")


def open_video_capture(index: int) -> cv2.VideoCapture:
    """
    Windows: mặc định thử MSMF trước (ổn định với index), rồi backend 0, rồi DirectShow.
    Nếu đặt PACKRECORDER_PREFER_DSHOW=1 thì thử DirectShow trước (một số máy mở nhanh hơn).
    """
    if sys.platform != "win32":
        return cv2.VideoCapture(index)

    cap_msmf = getattr(cv2, "CAP_MSMF", None)
    cap_dshow = getattr(cv2, "CAP_DSHOW", None)
    order: list[int] = []
    if _env_truthy("PACKRECORDER_PREFER_DSHOW"):
        if cap_dshow is not None:
            order.append(int(cap_dshow))
        if cap_msmf is not None:
            order.append(int(cap_msmf))
        order.append(0)
    else:
        if cap_msmf is not None:
            order.append(int(cap_msmf))
        order.append(0)
        if cap_dshow is not None:
            order.append(int(cap_dshow))

    seen: set[int] = set()
    uniq: list[int] = []
    for api in order:
        if api not in seen:
            seen.add(api)
            uniq.append(api)

    last: cv2.VideoCapture | None = None
    for api in uniq:
        cap = cv2.VideoCapture(index, api)
        last = cap
        if cap.isOpened():
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            return cap
        cap.release()
    return last if last is not None else cv2.VideoCapture(index)


def open_rtsp_capture(url: str) -> cv2.VideoCapture:
    """
    Mở luồng RTSP qua FFmpeg backend.

    - OPENCV_FFMPEG_RTSP_TRANSPORT: mặc định tcp (ổn định hơn udp trên LAN).
    - PACKRECORDER_RTSP_OPEN_TIMEOUT_MS / PACKRECORDER_RTSP_READ_TIMEOUT_MS: giới hạn chờ
      khi không kết nối được (tránh treo worker/UI khi dừng thread).
    """
    url = (url or "").strip()
    if not url:
        return cv2.VideoCapture()
    # region agent log
    try:
        from packrecorder.debug_ndjson import dbg, dbg_safe_url

        dbg_safe_url("H2", "opencv_video.open_rtsp_capture", url)
    except Exception:
        pass
    # endregion agent log
    os.environ.setdefault("OPENCV_FFMPEG_RTSP_TRANSPORT", "tcp")
    try:
        open_ms = int(os.environ.get("PACKRECORDER_RTSP_OPEN_TIMEOUT_MS", "8000"))
    except ValueError:
        open_ms = 8000
    try:
        read_ms = int(os.environ.get("PACKRECORDER_RTSP_READ_TIMEOUT_MS", "5000"))
    except ValueError:
        read_ms = 5000
    cap_ff = getattr(cv2, "CAP_FFMPEG", None)
    open_prop = getattr(cv2, "CAP_PROP_OPEN_TIMEOUT_MSEC", None)
    read_prop = getattr(cv2, "CAP_PROP_READ_TIMEOUT_MSEC", None)
    params: list[int] = []
    if open_prop is not None and open_ms > 0:
        params.extend([int(open_prop), open_ms])
    if read_prop is not None and read_ms > 0:
        params.extend([int(read_prop), read_ms])
    if cap_ff is not None:
        cap = (
            cv2.VideoCapture(url, int(cap_ff), params)
            if params
            else cv2.VideoCapture(url, int(cap_ff))
        )
    else:
        cap = cv2.VideoCapture(url)
    # region agent log
    try:
        from packrecorder.debug_ndjson import dbg

        dbg(
            "H2",
            "opencv_video.open_rtsp_capture.after_construct",
            "VideoCapture returned",
            opened=bool(cap.isOpened()),
            has_params=bool(params),
        )
    except Exception:
        pass
    # endregion agent log
    if cap.isOpened():
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
    return cap
