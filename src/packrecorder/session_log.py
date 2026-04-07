"""Log lỗi theo phiên: mỗi lần khởi động app xóa/ghi lại file, trong phiên chỉ thêm dòng."""

from __future__ import annotations

import sys
import time
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterator, Optional

_LOG_NAME = "run_errors.log"

_session_t0_mono: Optional[float] = None
_phase_t_mono: Optional[float] = None


def _log_dir() -> Path:
    """Thư mục ghi run_errors.log: cwd khi dev; cùng folder với .exe khi PyInstaller."""
    if getattr(sys, "frozen", False):
        exe = getattr(sys, "executable", None)
        if exe:
            return Path(exe).resolve().parent
    return Path.cwd()


def session_log_path() -> Path:
    return _log_dir() / _LOG_NAME


def reset_session_log() -> None:
    """Xóa nội dung cũ, mở phiên log mới (gọi một lần khi khởi động app)."""
    global _session_t0_mono, _phase_t_mono
    now = time.monotonic()
    _session_t0_mono = now
    _phase_t_mono = now
    p = session_log_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            f"=== Pack Recorder — phiên làm việc {datetime.now().isoformat()} ===\n"
            f"File này: {p.resolve()}\n"
            f"(Các dòng sau: T+ = giây từ lúc reset log; Δ+ = giây từ dòng log trước)\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def monotonic_since_session_start() -> Optional[float]:
    """Giây đã trôi từ reset_session_log(); None nếu chưa reset."""
    if _session_t0_mono is None:
        return None
    return time.monotonic() - _session_t0_mono


def stderr_timing_prefix() -> str:
    """Tiền tố cho print stderr: [T+Xs] """
    dt = monotonic_since_session_start()
    if dt is None:
        return ""
    return f"[T+{dt:.3f}s] "


def mark_session_phase(label: str) -> None:
    """Ghi mốc INFO vào run_errors (có T+ / Δ+ như mọi dòng)."""
    append_session_log("INFO", label)


def append_session_log(
    level: str,
    message: str,
    *,
    op_duration_s: Optional[float] = None,
) -> None:
    """Thêm một dòng (level = ERROR, WARNING, …)."""
    global _phase_t_mono
    try:
        p = session_log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().isoformat()
        now = time.monotonic()
        t0 = _session_t0_mono
        if t0 is None:
            t_since = 0.0
            d_since = 0.0
        else:
            t_since = now - t0
            p0 = _phase_t_mono if _phase_t_mono is not None else t0
            d_since = now - p0
        _phase_t_mono = now
        dur = ""
        if op_duration_s is not None:
            dur = f" (xử lý {op_duration_s:.3f}s)"
        line = (
            f"[{ts}] [T+{t_since:.3f}s] [Δ+{d_since:.3f}s] {level} {message}{dur}\n"
        )
        with p.open("a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
    except OSError:
        pass


@contextmanager
def session_log_timed(label: str) -> Iterator[None]:
    """Ghi vào log thời gian khối lệnh (INFO … với xử lý Xs)."""
    t0 = time.monotonic()
    try:
        yield
    finally:
        append_session_log("INFO", f"{label}", op_duration_s=time.monotonic() - t0)


def log_session_error(
    message: str,
    *,
    exc_info: Optional[tuple[type, BaseException, object]] = None,
) -> None:
    append_session_log("ERROR", message)
    if exc_info is None:
        return
    try:
        tb_text = "".join(traceback.format_exception(*exc_info))
        with session_log_path().open("a", encoding="utf-8") as f:
            f.write(tb_text)
            f.flush()
    except OSError:
        pass


_prev_excepthook: Optional[Callable[..., object]] = None
_hooks_installed = False


def _excepthook(exc_type: type, exc: BaseException, tb: object) -> None:
    try:
        log_session_error(
            f"Ngoại lệ chưa bắt ({exc_type.__name__}): {exc}",
            exc_info=(exc_type, exc, tb),
        )
    except Exception:
        pass
    if _prev_excepthook is not None:
        _prev_excepthook(exc_type, exc, tb)


def enable_native_crash_dump() -> None:
    """Ghi stack Python khi crash C-level (OpenCV/Qt DLL). File cạnh run_errors.log."""
    import faulthandler

    try:
        path = session_log_path().parent / "native_crash.txt"
        fh = path.open("w", encoding="utf-8")
        faulthandler.enable(fh)
        append_session_log(
            "INFO",
            f"faulthandler: crash native (SIGSEGV/abort) ghi vào {path.resolve()}",
        )
    except OSError:
        faulthandler.enable(sys.stderr)


def install_runtime_error_hooks() -> None:
    """sys.excepthook + Qt Warning/Critical → run_errors.log."""
    global _prev_excepthook, _hooks_installed
    if not _hooks_installed:
        _hooks_installed = True
        _prev_excepthook = sys.excepthook
        sys.excepthook = _excepthook

    try:
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler
    except ImportError:
        return

    def qt_handler(msg_type: QtMsgType, _context: object, message: str) -> None:
        if msg_type <= QtMsgType.QtInfoMsg:
            return
        if msg_type == QtMsgType.QtWarningMsg:
            lvl = "WARNING"
        elif msg_type in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
            lvl = "ERROR"
        else:
            lvl = "QT"
        try:
            append_session_log(lvl, message)
        except Exception:
            pass

    qInstallMessageHandler(qt_handler)
