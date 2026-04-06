from __future__ import annotations

import time
from collections.abc import Callable
from typing import Optional

import cv2
from PySide6.QtCore import QThread, Signal

try:
    from pyzbar.pyzbar import decode as zbar_decode
except ImportError:
    zbar_decode = None  # type: ignore[misc, assignment]


class ScanWorker(QThread):
    """OpenCV capture; optional pyzbar decode; frame_ready only while recording."""

    decoded = Signal(int, str)
    frame_ready = Signal(int, bytes)
    camera_opened = Signal(int, int, int, int)

    def __init__(
        self,
        camera_index: int,
        *,
        debounce_s: float = 0.35,
        decode_enabled: bool = True,
        is_shutdown_countdown: Optional[Callable[[], bool]] = None,
    ) -> None:
        super().__init__()
        self._camera_index = camera_index
        self._debounce_s = debounce_s
        self._decode_enabled = decode_enabled
        self._is_shutdown_countdown = is_shutdown_countdown or (lambda: False)
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
            cap = cv2.VideoCapture(self._camera_index)
            if cap.isOpened():
                w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
                h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
                fps = int(cap.get(cv2.CAP_PROP_FPS)) or 15
                if fps <= 0 or fps > 60:
                    fps = 15
                self.camera_opened.emit(self._camera_index, w, h, fps)
            while self._running:
                if not cap or not cap.isOpened():
                    time.sleep(0.2)
                    continue
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.02)
                    continue
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
        finally:
            if cap is not None and cap.isOpened():
                cap.release()
