from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class ScannerModeDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Cài đặt máy quét")
        self.resize(920, 680)

        self._desc = QLabel()
        self._desc.setWordWrap(True)
        self._desc.setStyleSheet("font-size:13px;color:#202020;")

        self._img = QLabel("Không tìm thấy ảnh mã cấu hình.")
        self._img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img.setMinimumHeight(560)

        btn_bg = QPushButton("Mã 1: Chạy ngầm")
        btn_normal = QPushButton("Mã 2: Bình thường")
        btn_bg.setMinimumHeight(36)
        btn_normal.setMinimumHeight(36)
        btn_bg.setStyleSheet("font-weight:600;padding:4px 12px;")
        btn_normal.setStyleSheet("font-weight:600;padding:4px 12px;")
        btn_bg.clicked.connect(lambda: self._set_mode(background=True))
        btn_normal.clicked.connect(lambda: self._set_mode(background=False))

        top = QHBoxLayout()
        top.addWidget(btn_bg)
        top.addWidget(btn_normal)
        top.addStretch(1)

        root = QVBoxLayout(self)
        root.addLayout(top)
        root.addWidget(self._desc)
        root.addWidget(self._img, 1)

        self._set_mode(background=True)

    def _asset_path(self) -> Path:
        here = Path(__file__).resolve()
        return here.parents[3] / "docs" / "scanner-config-codes" / "winson-config-page-1.png"

    def _set_mode(self, *, background: bool) -> None:
        mode_text = (
            "Mã 1 đang hiển thị: chuyển máy quét sang chế độ chạy ngầm (HID POS)."
            if background
            else "Mã 2 đang hiển thị: chuyển máy quét về chế độ bình thường."
        )
        self._desc.setText(mode_text + " Chỉ hiển thị một mã để tránh quét nhầm.")

        p = self._asset_path()
        if not p.is_file():
            self._img.setText("Không tìm thấy ảnh mã cấu hình.")
            self._img.setPixmap(QPixmap())
            return
        pix = QPixmap(str(p))
        if pix.isNull():
            self._img.setText("Không tải được ảnh mã cấu hình.")
            self._img.setPixmap(QPixmap())
            return
        scaled = pix.scaled(
            860,
            560,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._img.setPixmap(scaled)
