"""Quét camera OpenCV trên luồng nền — tránh chặn UI hàng chục giây trên Windows."""

from __future__ import annotations

import sys
from typing import Optional, Set

from PySide6.QtCore import QThread, Signal

from packrecorder.camera_probe import probe_opencv_camera_indices
from packrecorder.session_log import log_session_error


class CameraProbeThread(QThread):
    indices_ready = Signal(list)

    def __init__(
        self,
        parent=None,
        *,
        skip_open_for_indices: Optional[Set[int]] = None,
    ) -> None:
        super().__init__(parent)
        self._skip = frozenset(skip_open_for_indices or ())

    def run(self) -> None:
        try:
            found = probe_opencv_camera_indices(
                max_index=6,
                require_frame=False,
                skip_open_for_indices=set(self._skip),
            )
        except Exception:
            log_session_error(
                "CameraProbeThread: lỗi Python khi quét camera (driver/OpenCV).",
                exc_info=sys.exc_info(),
            )
            found = []
        self.indices_ready.emit(found)
