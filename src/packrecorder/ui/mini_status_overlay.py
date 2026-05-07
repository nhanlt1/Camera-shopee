from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

MiniOverlayLineKind = str  # "idle" | "recording" | "error"


def line_style_stylesheet(kind: str) -> str:
    """Stylesheet cho một dòng overlay (spec §6.2b — màu theo trạng thái)."""
    base = (
        "font-size:10pt;font-family:'Segoe UI Variable',Segoe UI,Consolas,"
        "'Cascadia Mono',sans-serif;font-weight:600;"
    )
    if kind == "recording":
        return (
            base
            + "color:#0e700e;background-color:#dff6dd;padding:6px 10px;"
            "border-radius:8px;border:1px solid #107c10;"
        )
    if kind == "error":
        return (
            base
            + "color:#8f0804;background-color:#fde7e9;padding:6px 10px;"
            "border-radius:8px;border:1px solid #c42b1c;"
        )
    return (
        base
        + "color:#202020;background-color:#f3f3f3;padding:6px 10px;"
        "border-radius:8px;border:1px solid #e5e5e5;"
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
        lay.setContentsMargins(12, 10, 12, 10)
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

    def set_second_line_visible(self, visible: bool) -> None:
        """Một quầy: ẩn dòng thứ hai để overlay gọn."""
        self._line2.setVisible(bool(visible))

    def set_click_through(self, on: bool) -> None:
        self._click_through = bool(on)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, on)

    def mouseDoubleClickEvent(self, event) -> None:
        if not self._click_through:
            self.request_restore_main.emit()
        super().mouseDoubleClickEvent(event)
