from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMainWindow

from packrecorder.ui.main_window import MainWindow


def _debug_log(line: str) -> None:
    try:
        base = os.environ.get("LOCALAPPDATA", str(Path.home()))
        p = Path(base) / "PackRecorder" / "last_run.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()} {line}\n")
    except OSError:
        pass


def _center_on_screen(app: QApplication, window: QMainWindow) -> None:
    screen = app.primaryScreen()
    if screen is None:
        return
    ag = screen.availableGeometry()
    fg = window.frameGeometry()
    fg.moveCenter(ag.center())
    window.move(fg.topLeft())


def run_app() -> int:
    _debug_log("run_app: bat dau")
    print(
        "PackRecorder: đang mở cửa sổ… "
        "(không thấy thì thử Alt+Tab; nếu chạy từ Cursor mà vẫn không có UI, "
        "bấm đúp run_packrecorder.bat hoặc run_packrecorder_console.bat trong thư mục project.)",
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
    _debug_log("run_app: da show MainWindow, vao vong lap su kien")
    code = app.exec()
    _debug_log(f"run_app: thoat ma {code}")
    return code
