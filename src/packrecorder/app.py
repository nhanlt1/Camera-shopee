from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from packrecorder.ui.main_window import MainWindow


def run_app() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("PackRecorder")
    app.setStyle("Fusion")
    qss = Path(__file__).resolve().parent / "ui" / "styles.qss"
    if qss.is_file():
        app.setStyleSheet(qss.read_text(encoding="utf-8"))
    w = MainWindow()
    w.show()
    return app.exec()
