from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMainWindow

from packrecorder.ui.main_window import MainWindow


def _center_on_screen(app: QApplication, window: QMainWindow) -> None:
    screen = app.primaryScreen()
    if screen is None:
        return
    ag = screen.availableGeometry()
    fg = window.frameGeometry()
    fg.moveCenter(ag.center())
    window.move(fg.topLeft())


def run_app() -> int:
    print(
        "PackRecorder: đang mở cửa sổ… "
        "(không thấy thì thử Alt+Tab; nếu chạy từ Cursor mà vẫn không có UI, "
        "mở PowerShell/CMD riêng và chạy: .\\.venv\\Scripts\\python.exe -m packrecorder)",
        file=sys.stderr,
    )
    app = QApplication(sys.argv)
    app.setApplicationName("PackRecorder")
    app.setStyle("Fusion")
    qss = Path(__file__).resolve().parent / "ui" / "styles.qss"
    if qss.is_file():
        app.setStyleSheet(qss.read_text(encoding="utf-8"))
    w = MainWindow()
    w.setMinimumSize(520, 240)
    w.resize(780, 440)
    _center_on_screen(app, w)
    w.show()
    w.raise_()
    w.activateWindow()
    QTimer.singleShot(0, w.raise_)
    QTimer.singleShot(0, w.activateWindow)
    return app.exec()
