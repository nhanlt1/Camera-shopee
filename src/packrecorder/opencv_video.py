"""Mở VideoCapture ổn định trên Windows (MSMF trước, tránh lỗi DSHOW + index)."""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Optional

# Phải đặt trước `import cv2` để giảm log C++ (FFmpeg/DShow) lúc nạp module.
os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")
# Giảm độ trễ / treo khi mở webcam qua MSMF (đặt trước import cv2).
os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")
# Tránh FFmpeg videoio thử liệt kê DSHOW (WARN cap_ffmpeg_impl / Failed list devices for backend dshow).
os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_MSMF", "9999")
os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_DSHOW", "5000")
os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_FFMPEG", "1")

import cv2


def safe_video_capture_read(cap: cv2.VideoCapture) -> tuple[bool, Optional[Any]]:
    """Đọc khung — driver/USB hotplug có thể ném cv2.error thay vì trả ok=False."""
    try:
        ok, frame = cap.read()
        return ok, frame
    except cv2.error:
        return False, None


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


def _capture_delivers_bgr_frame(cap: cv2.VideoCapture, *, attempts: int = 8) -> bool:
    """
    MSMF đôi khi isOpened()=True nhưng read() không ra khung — bỏ backend đó và thử tiếp.
    PACKRECORDER_SKIP_CAPTURE_VALIDATE=1: bỏ qua (một vài driver chậm / khác thường).
    """
    n = max(1, int(attempts))
    for _ in range(n):
        ok, frame = safe_video_capture_read(cap)
        if (
            ok
            and frame is not None
            and getattr(frame, "ndim", 0) == 3
            and int(frame.shape[2]) >= 3
        ):
            return True
        time.sleep(0.02)
    return False


def open_video_capture(index: int) -> cv2.VideoCapture:
    """
    Windows: thử MSMF rồi DirectShow — không dùng CAP_ANY (0): một số bản OpenCV
    sẽ đi qua FFmpeg và in WARN «Failed list devices for backend dshow», đôi khi mở cam lỗi.
    PACKRECORDER_PREFER_DSHOW=1: thử DirectShow trước.
    PACKRECORDER_SKIP_CAPTURE_VALIDATE=1: không đọc thử khung (hành vi cũ; chỉ khi validate làm hỏng driver).
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
    else:
        if cap_msmf is not None:
            order.append(int(cap_msmf))
        if cap_dshow is not None:
            order.append(int(cap_dshow))

    seen: set[int] = set()
    uniq: list[int] = []
    for api in order:
        if api not in seen:
            seen.add(api)
            uniq.append(api)

    validate = not _env_truthy("PACKRECORDER_SKIP_CAPTURE_VALIDATE")
    for api in uniq:
        cap = cv2.VideoCapture(index, api)
        if not cap.isOpened():
            cap.release()
            continue
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        if validate and not _capture_delivers_bgr_frame(cap):
            try:
                cap.release()
            except Exception:
                pass
            continue
        return cap
    # Camera rất chậm / driver lạ: thử lại không validate (như bản cũ).
    for api in uniq:
        cap = cv2.VideoCapture(index, api)
        if not cap.isOpened():
            cap.release()
            continue
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
        return cap
    if cap_msmf is not None:
        return cv2.VideoCapture(index, int(cap_msmf))
    if cap_dshow is not None:
        return cv2.VideoCapture(index, int(cap_dshow))
    return cv2.VideoCapture(index)


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
    if cap.isOpened():
        try:
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass
    return cap
