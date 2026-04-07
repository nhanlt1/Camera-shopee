from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import Optional

from PySide6.QtCore import QThread, Signal

# Nạp opencv_video trước cv2: module đặt OPENCV_LOG_LEVEL rồi mới import cv2.
from packrecorder.opencv_video import configure_opencv_logging, open_video_capture
from packrecorder.session_log import log_session_error

import cv2

configure_opencv_logging()

try:
    from pyzbar.pyzbar import decode as zbar_decode
except ImportError:
    zbar_decode = None  # type: ignore[misc, assignment]

# Bỏ khung đầu sau mở camera (MSMF/OpenCV thường trả đen vài frame).
_WARMUP_FRAMES_MIN = 5
_WARMUP_FRAMES_MAX = 15
# Nhiều webcam (MSMF) trả CAP_PROP_FPS = 0; 30 gần tốc độ thật hơn 15.
_FALLBACK_CAPTURE_FPS = 30


class ScanWorker(QThread):
    """OpenCV capture; optional pyzbar decode; frame_ready only while recording."""

    decoded = Signal(int, str)
    frame_ready = Signal(int, bytes)
    """BGR frame cho xem trước UI (không cần đang ghi)."""
    preview_ready = Signal(int, bytes)
    camera_opened = Signal(int, int, int, int)

    def __init__(
        self,
        camera_index: int,
        *,
        debounce_s: float = 0.35,
        decode_enabled: bool = True,
        is_shutdown_countdown: Optional[Callable[[], bool]] = None,
        preview_fps: float = 8.0,
    ) -> None:
        super().__init__()
        self._camera_index = camera_index
        self._debounce_s = debounce_s
        self._decode_enabled = decode_enabled
        self._is_shutdown_countdown = is_shutdown_countdown or (lambda: False)
        self._preview_min_s = (1.0 / preview_fps) if preview_fps > 0 else 0.0
        self._last_preview_mono = 0.0
        self._running = True
        self._recording = False

    @property
    def camera_index(self) -> int:
        return self._camera_index

    def stop_worker(self) -> None:
        self._running = False

    def set_recording(self, on: bool) -> None:
        self._recording = on

    def run(self) -> None:
        cap: Optional[cv2.VideoCapture] = None
        last_code: Optional[str] = None
        last_emit_mono = 0.0
        try:
            configure_opencv_logging()
            cap = open_video_capture(self._camera_index)
            preview_warmup_left = 0
            if cap.isOpened():
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
                fps = int(cap.get(cv2.CAP_PROP_FPS)) or _FALLBACK_CAPTURE_FPS
                if fps <= 0 or fps > 60:
                    fps = _FALLBACK_CAPTURE_FPS
                self.camera_opened.emit(self._camera_index, w, h, fps)
                preview_warmup_left = min(
                    _WARMUP_FRAMES_MAX, max(_WARMUP_FRAMES_MIN, fps)
                )
            while self._running:
                if not cap or not cap.isOpened():
                    time.sleep(0.2)
                    continue
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.02)
                    continue
                if preview_warmup_left > 0:
                    preview_warmup_left -= 1
                if self._preview_min_s > 0 and preview_warmup_left == 0:
                    now_prev = time.monotonic()
                    if now_prev - self._last_preview_mono >= self._preview_min_s:
                        self._last_preview_mono = now_prev
                        self.preview_ready.emit(self._camera_index, frame.tobytes())
                if self._recording:
                    self.frame_ready.emit(self._camera_index, frame.tobytes())
                if not self._decode_enabled or zbar_decode is None:
                    continue
                try:
                    results = zbar_decode(frame)
                except Exception:
                    continue
                now = time.monotonic()
                for obj in results:
                    try:
                        raw = obj.data.decode("utf-8", errors="replace").strip()
                    except Exception:
                        continue
                    if not raw:
                        continue
                    if self._is_shutdown_countdown():
                        self.decoded.emit(self._camera_index, raw)
                        last_code = None
                        continue
                    if raw == last_code and (now - last_emit_mono) < self._debounce_s:
                        continue
                    last_code = raw
                    last_emit_mono = now
                    self.decoded.emit(self._camera_index, raw)
        except Exception:
            log_session_error(
                f"ScanWorker (camera {self._camera_index}) lỗi trong run().",
                exc_info=sys.exc_info(),
            )
        finally:
            if cap is not None and cap.isOpened():
                cap.release()
