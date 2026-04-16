from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

MiniOverlayLineKind = str  # "idle" | "recording" | "error"


def line_style_stylesheet(kind: str) -> str:
    """Stylesheet cho một dòng overlay (spec §6.2b — màu theo trạng thái)."""
    base = (
        "font-size:10pt;font-family:Segoe UI,Consolas,'Cascadia Mono',sans-serif;"
    )
    if kind == "recording":
        return (
            base
            + "color:#c8e6c9;background-color:#1b5e20;padding:4px 8px;border-radius:4px;"
        )
    if kind == "error":
        return (
            base
            + "color:#ffebee;background-color:#b71c1c;padding:4px 8px;border-radius:4px;"
        )
    return (
        base
        + "color:#eceff1;background-color:#37474f;padding:4px 8px;border-radius:4px;"
    )


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
            lb.setStyleSheet(line_style_stylesheet("idle"))
        lay.addWidget(self._line1)
        lay.addWidget(self._line2)

    def set_lines(self, line1: str, line2: str) -> None:
        self.set_lines_styled(
            (line1, line2),
            ("idle", "idle"),
        )

    def set_lines_styled(
        self,
        texts: tuple[str, str],
        kinds: tuple[str, str],
    ) -> None:
        self._line1.setText(texts[0])
        self._line2.setText(texts[1])
        self._line1.setStyleSheet(line_style_stylesheet(kinds[0]))
        self._line2.setStyleSheet(line_style_stylesheet(kinds[1]))

    def set_click_through(self, on: bool) -> None:
        self._click_through = bool(on)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, on)

    def mouseDoubleClickEvent(self, event) -> None:
        if not self._click_through:
            self.request_restore_main.emit()
        super().mouseDoubleClickEvent(event)
