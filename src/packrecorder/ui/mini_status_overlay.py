from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class MiniStatusOverlay(QWidget):
    """Hai dòng trạng thái quầy khi cửa sổ chính thu nhỏ / ẩn (spec 6.2b)."""

    request_restore_main = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self._click_through = False
        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 8, 10, 8)
        self._line1 = QLabel("Máy 1: —")
        self._line2 = QLabel("Máy 2: —")
        for lb in (self._line1, self._line2):
            f = QFont()
            f.setPointSize(10)
            lb.setFont(f)
            lb.setStyleSheet("color:#eceff1;background-color:#37474f;padding:4px 8px;border-radius:4px;")
        lay.addWidget(self._line1)
        lay.addWidget(self._line2)

    def set_lines(self, line1: str, line2: str) -> None:
        self._line1.setText(line1)
        self._line2.setText(line2)

    def set_click_through(self, on: bool) -> None:
        self._click_through = bool(on)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, on)

    def mouseDoubleClickEvent(self, event) -> None:
        if not self._click_through:
            self.request_restore_main.emit()
        super().mouseDoubleClickEvent(event)
