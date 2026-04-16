from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QLabel, QPushButton, QVBoxLayout, QWidget

from packrecorder.config import WINSON_MODE_USB_COM


class WinsonComQrPanel(QWidget):
    """QR + hướng dẫn USB COM khi chưa thấy cổng (spec §6.3)."""

    def __init__(self, repo_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        png = (
            repo_root
            / "docs"
            / "scanner-config-codes"
            / "winson-mode-barcodes"
            / "qr-usb-com.png"
        )
        lay = QVBoxLayout(self)
        self._img = QLabel()
        self._img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = QPixmap(str(png))
        if not pix.isNull():
            self._img.setPixmap(
                pix.scaled(
                    200,
                    200,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self._txt = QLabel(
            "Không thấy cổng COM. Cần chế độ USB COM — quét mã sau bằng máy Winson:\n"
            f"{WINSON_MODE_USB_COM}"
        )
        self._txt.setWordWrap(True)
        self._btn = QPushButton("Thử lại / Làm mới thiết bị")
        lay.addWidget(self._img)
        lay.addWidget(self._txt)
        lay.addWidget(self._btn)

    def set_on_refresh(self, callback) -> None:
        try:
            self._btn.clicked.disconnect()
        except TypeError:
            pass
        self._btn.clicked.connect(callback)
