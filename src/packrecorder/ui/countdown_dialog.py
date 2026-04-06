from __future__ import annotations

import subprocess
import sys
from datetime import datetime

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QDialog, QLabel, QPushButton, QVBoxLayout

from packrecorder.shutdown_scheduler import defer_one_hour


class ShutdownCountdownDialog(QDialog):
    """60s countdown; any barcode scan cancels shutdown (handled in MainWindow)."""

    scan_cancelled = Signal()
    shutdown_committed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tắt máy")
        self._seconds_left = 60
        self._label = QLabel()
        self._label.setMinimumWidth(320)
        self._update_label()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._next_shutdown_holder: list[datetime | None] = [None]

        layout = QVBoxLayout(self)
        layout.addWidget(self._label)
        abort = QPushButton("Hủy tắt máy (hoặc quét mã)")
        abort.clicked.connect(self._on_manual_cancel)
        layout.addWidget(abort)

    def set_next_shutdown_ref(self, ref: list[datetime | None]) -> None:
        self._next_shutdown_holder = ref

    def start_countdown(self) -> None:
        self._seconds_left = 60
        self._update_label()
        self._timer.start(1000)

    def _update_label(self) -> None:
        self._label.setText(
            f"Tắt máy sau {self._seconds_left} giây.\nQuét bất kỳ mã hợp lệ để hủy."
        )

    def _tick(self) -> None:
        self._seconds_left -= 1
        self._update_label()
        if self._seconds_left <= 0:
            self._timer.stop()
            self.shutdown_committed.emit()
            self._run_shutdown()
            self.accept()

    def _on_manual_cancel(self) -> None:
        self._cancel_shutdown()

    def on_barcode_during_countdown(self) -> None:
        self._cancel_shutdown()

    def _cancel_shutdown(self) -> None:
        self._timer.stop()
        now = datetime.now()
        if self._next_shutdown_holder:
            self._next_shutdown_holder[0] = defer_one_hour(now)
        self.scan_cancelled.emit()
        self.reject()

    def _run_shutdown(self) -> None:
        if sys.platform != "win32":
            return
        kwargs: dict = {"check": False}
        if hasattr(subprocess, "CREATE_NO_WINDOW"):
            kwargs["creationflags"] = subprocess.CREATE_NO_WINDOW
        subprocess.run(["shutdown", "/s", "/t", "0"], **kwargs)
