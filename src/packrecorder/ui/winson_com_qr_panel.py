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
        barcode_png = (
            repo_root
            / "docs"
            / "scanner-config-codes"
            / "winson-mode-barcodes"
            / "code128-usb-com.png"
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
        self._barcode = QLabel()
        self._barcode.setAlignment(Qt.AlignmentFlag.AlignCenter)
        bpix = QPixmap(str(barcode_png))
        if not bpix.isNull():
            self._barcode.setPixmap(
                bpix.scaledToWidth(
                    260,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self._txt = QLabel(
            "Nếu bạn không tìm thấy máy quét hãy cho máy quét scan qrcode hoặc barcode bên dưới\n"
            "-> chuyển máy quét sang chế độ COM (chạy ẩn theo phần mềm)\n"
            f"Mã COM: {WINSON_MODE_USB_COM}"
        )
        self._txt.setWordWrap(True)
        self._btn = QPushButton("Thử lại / Làm mới thiết bị")
        self._txt_code = QLabel(WINSON_MODE_USB_COM)
        self._txt_code.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._txt_code.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        lay.addWidget(self._img)
        lay.addWidget(self._barcode)
        lay.addWidget(self._txt)
        lay.addWidget(self._txt_code)
        lay.addWidget(self._btn)

    def set_on_refresh(self, callback) -> None:
        try:
            self._btn.clicked.disconnect()
        except TypeError:
            pass
        self._btn.clicked.connect(callback)
