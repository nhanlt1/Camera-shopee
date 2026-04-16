from __future__ import annotations

from dataclasses import dataclass

import cv2
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from packrecorder.opencv_video import open_rtsp_capture, open_video_capture


@dataclass(frozen=True)
class PreviewRequest:
    source: str  # "usb" | "rtsp"
    usb_index: int
    rtsp_url: str


class SingleFramePreviewThread(QThread):
    """Open source briefly, grab one frame, then release."""

    preview_ready = Signal(bool, str, object)  # ok, message, QImage | None

    def __init__(self, request: PreviewRequest, parent=None) -> None:
        super().__init__(parent)
        self._request = request

    @classmethod
    def for_usb(cls, index: int, parent=None) -> "SingleFramePreviewThread":
        return cls(PreviewRequest("usb", int(index), ""), parent=parent)

    @classmethod
    def for_rtsp(cls, url: str, parent=None) -> "SingleFramePreviewThread":
        return cls(PreviewRequest("rtsp", 0, (url or "").strip()), parent=parent)

    def run(self) -> None:
        req = self._request
        if req.source == "rtsp":
            if not req.rtsp_url:
                self.preview_ready.emit(False, "Nhập URL RTSP trước khi xem trước.", None)
                return
            cap = open_rtsp_capture(req.rtsp_url)
            title = "RTSP"
        else:
            cap = open_video_capture(int(req.usb_index))
            title = f"USB {req.usb_index}"
        try:
            if not cap.isOpened():
                self.preview_ready.emit(
                    False,
                    f"Không mở được nguồn {title}.",
                    None,
                )
                return
            frame = None
            for _ in range(8):
                ok, frm = cap.read()
                if ok and frm is not None and frm.size > 0:
                    frame = frm
                    break
            if frame is None:
                self.preview_ready.emit(
                    False,
                    f"{title}: mở được nhưng chưa nhận khung hình.",
                    None,
                )
                return
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w = rgb.shape[:2]
            img = QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
            self.preview_ready.emit(True, f"{title}: xem trước {w}x{h}.", img)
        finally:
            try:
                cap.release()
            except Exception:
                pass
