from __future__ import annotations

from typing import Optional

import numpy as np

from packrecorder.opencv_video import configure_opencv_logging, open_video_capture
from packrecorder.record_resolution import apply_capture_resolution

import cv2

configure_opencv_logging()
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QLabel


def bgr_bytes_to_pixmap(
    bgr_bytes: bytes,
    width: int,
    height: int,
    max_w: int = 520,
    *,
    fast_scale: bool = True,
) -> Optional[QPixmap]:
    """Chuyển buffer BGR OpenCV (h*w*3) sang QPixmap co giữ tỉ lệ."""
    need = width * height * 3
    if width <= 0 or height <= 0 or len(bgr_bytes) != need:
        return None
    try:
        bgr = np.frombuffer(bgr_bytes, dtype=np.uint8).reshape((height, width, 3))
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    except Exception:
        return None
    rgb = np.ascontiguousarray(rgb)
    h, w = rgb.shape[:2]
    qimg = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888)
    pix = QPixmap.fromImage(qimg)
    mode = (
        Qt.TransformationMode.FastTransformation
        if fast_scale
        else Qt.TransformationMode.SmoothTransformation
    )
    return pix.scaled(
        max_w,
        int(max_w * h / w) if w else max_w,
        Qt.AspectRatioMode.KeepAspectRatio,
        mode,
    )


class CameraPreviewLabel(QLabel):
    """Live preview từ OpenCV VideoCapture (chạy trên luồng UI + QTimer)."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumSize(400, 225)
        self.setStyleSheet(
            "background:#1a1a1a;color:#9e9e9e;border:1px solid #424242;border-radius:4px;"
        )
        self.setText("Chưa chọn camera")
        self._cap: Optional[cv2.VideoCapture] = None
        self._index: int = -1
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._grab_frame)
        self._max_w = 480

    def set_camera_index(
        self,
        index: int,
        *,
        capture_target_wh: tuple[int, int] | None = None,
    ) -> None:
        self.stop()
        self._index = index
        self.setText(f"Đang mở camera {index}…")
        configure_opencv_logging()
        self._cap = open_video_capture(index)
        if self._cap is None or not self._cap.isOpened():
            if self._cap is not None:
                self._cap.release()
                self._cap = None
            self.setText(f"Không mở được camera {index}")
            return
        if capture_target_wh is not None:
            try:
                apply_capture_resolution(
                    self._cap, capture_target_wh[0], capture_target_wh[1]
                )
            except Exception:
                pass
        self.setText("")
        self._timer.start(33)

    def stop(self) -> None:
        self._timer.stop()
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None

    def _grab_frame(self) -> None:
        if self._cap is None or not self._cap.isOpened():
            return
        ok, frame = self._cap.read()
        if not ok or frame is None:
            return
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        except Exception:
            return
        h, w = rgb.shape[:2]
        if w <= 0 or h <= 0:
            return
        rgb = np.ascontiguousarray(rgb)
        qimg = QImage(
            rgb.data,
            w,
            h,
            3 * w,
            QImage.Format.Format_RGB888,
        )
        pix = QPixmap.fromImage(qimg)
        self.setPixmap(
            pix.scaled(
                self._max_w,
                int(self._max_w * h / w) if w else 270,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
