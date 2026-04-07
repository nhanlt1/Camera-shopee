from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QMainWindow

from packrecorder.session_log import (
    append_startup_hints,
    enable_native_crash_dump,
    install_runtime_error_hooks,
    mark_session_phase,
    monotonic_since_session_start,
    reset_session_log,
    session_log_path,
    session_log_timed,
    stderr_timing_prefix,
)
from packrecorder.ui.main_window import MainWindow


def _debug_log(line: str) -> None:
    try:
        base = os.environ.get("LOCALAPPDATA", str(Path.home()))
        p = Path(base) / "PackRecorder" / "last_run.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        gap = monotonic_since_session_start()
        extra = f" [T+{gap:.3f}s]" if gap is not None else ""
        with p.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat()}{extra} {line}\n")
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


def _ensure_qt_plugins_frozen() -> None:
    if not getattr(sys, "frozen", False):
        return
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        _debug_log("frozen: khong co _MEIPASS")
        return
    plugins = Path(meipass) / "PySide6" / "plugins"
    ok = plugins.is_dir()
    _debug_log(f"frozen: _MEIPASS={meipass} plugins_dir_ok={ok} path={plugins}")
    if ok:
        os.environ.setdefault("QT_PLUGIN_PATH", str(plugins))
    else:
        _debug_log("frozen: CANH BAO thieu PySide6/plugins — exe co the tat ngay sau khi chay")


def _apply_readable_app_font(app: QApplication) -> None:
    """Font hệ thống rõ ràng — tránh chữ 'mất' khi QSS/Fusion không gán palette đúng."""
    f = QFont("Segoe UI", 9)
    if sys.platform == "win32":
        if not f.exactMatch():
            f = QFont("Microsoft YaHei UI", 9)
        if not f.exactMatch():
            f = QFont("MS Shell Dlg 2", 9)
    elif not f.exactMatch():
        f = QFont()
        f.setPointSize(9)
    app.setFont(f)


def _windows_bring_to_front(window: QMainWindow) -> None:
    """Dua cua so len truoc (Windows hay de app chay nhung khong nhin thay)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        window.raise_()
        window.activateWindow()
        hwnd = int(window.winId())
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        foreground = user32.GetForegroundWindow()
        fg_tid = user32.GetWindowThreadProcessId(foreground, None)
        cur_tid = kernel32.GetCurrentThreadId()
        if fg_tid and fg_tid != cur_tid:
            user32.AttachThreadInput(cur_tid, fg_tid, True)
        user32.SetForegroundWindow(hwnd)
        if fg_tid and fg_tid != cur_tid:
            user32.AttachThreadInput(cur_tid, fg_tid, False)
    except Exception:
        pass


def run_app() -> int:
    reset_session_log()
    install_runtime_error_hooks()
    enable_native_crash_dump()
    mark_session_phase("Đã reset run_errors.log và gắn hooks (excepthook / Qt).")
    _ensure_qt_plugins_frozen()
    mark_session_phase("Chuẩn bị frozen Qt plugins (nếu có).")
    _debug_log("run_app: bat dau")
    log_err = session_log_path().resolve()
    print(
        f"{stderr_timing_prefix()}PackRecorder: đang mở cửa sổ… "
        "(không thấy thì thử Alt+Tab; nếu chạy từ Cursor mà vẫn không có UI, "
        "bấm đúp run_packrecorder.bat hoặc run_packrecorder_console.bat trong thư mục project.)",
        file=sys.stderr,
    )
    print(
        f"{stderr_timing_prefix()}PackRecorder: log lỗi phiên (mỗi lần mở app ghi lại từ đầu): {log_err}",
        file=sys.stderr,
    )
    t_qt = time.monotonic()
    app = QApplication(sys.argv)
    app.setApplicationName("PackRecorder")
    app.setStyle("Fusion")
    _apply_readable_app_font(app)
    qss = Path(__file__).resolve().parent / "ui" / "styles.qss"
    if qss.is_file():
        app.setStyleSheet(qss.read_text(encoding="utf-8"))
    mark_session_phase(
        f"QApplication + stylesheet ({time.monotonic() - t_qt:.3f}s)"
    )
    with session_log_timed("Khởi tạo MainWindow()"):
        w = MainWindow()
    t_show = time.monotonic()
    _center_on_screen(app, w)
    w.show()
    w.raise_()
    w.activateWindow()
    _windows_bring_to_front(w)
    QTimer.singleShot(0, w.raise_)
    QTimer.singleShot(0, w.activateWindow)
    QTimer.singleShot(0, lambda: _windows_bring_to_front(w))
    QTimer.singleShot(250, lambda: _windows_bring_to_front(w))
    QTimer.singleShot(800, lambda: _windows_bring_to_front(w))
    mark_session_phase(
        f"Đã show cửa sổ + lên lớp ({time.monotonic() - t_show:.3f}s)"
    )
    _debug_log("run_app: da show MainWindow, vao vong lap su kien")

    def _heartbeat(phase: str) -> None:
        mark_session_phase(phase)

    def _about_to_quit_dbg() -> None:
        mark_session_phase(
            "QApplication.aboutToQuit — ứng dụng kết thúc vòng lặp sự kiện."
        )
        # region agent log
        try:
            from packrecorder.debug_ndjson import dbg

            dbg("H3", "app.run_app.aboutToQuit", "aboutToQuit fired")
        except Exception:
            pass
        # endregion agent log

    app.aboutToQuit.connect(_about_to_quit_dbg)
    QTimer.singleShot(
        400,
        lambda: _heartbeat(
            "Heartbeat ~0.4s sau khi show — process còn chạy (nếu không thấy dòng này: crash native hoặc kill từ bên ngoài)."
        ),
    )
    QTimer.singleShot(
        3000,
        lambda: _heartbeat("Heartbeat ~3s — UI loop vẫn chạy."),
    )
    mark_session_phase("Bắt đầu QApplication.exec().")
    append_startup_hints()
    t_exec = time.monotonic()
    code = app.exec()
    mark_session_phase(
        f"Vòng lặp sự kiện kết thúc, mã {code} (chạy {time.monotonic() - t_exec:.3f}s)"
    )
    _debug_log(f"run_app: thoat ma {code}")
    return code
