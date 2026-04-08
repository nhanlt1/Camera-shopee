from __future__ import annotations

import os
import sys
import traceback
from pathlib import Path


def _packrecorder_data_dir() -> Path:
    return Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "PackRecorder"


def _show_windows_error(message: str) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            0,
            message[:2048],
            "Pack Recorder — lỗi",
            0x10,
        )
    except Exception:
        pass


def main() -> None:
    # Trước khi import cv2 (kéo theo từ app → main_window → scan_worker).
    # SILENT: bớt spam VIDEOIO/FFmpeg/obsensor khi quét index camera.
    os.environ.setdefault("OPENCV_LOG_LEVEL", "SILENT")
    os.environ.setdefault("OPENCV_VIDEOIO_DEBUG", "0")
    # MSMF: tắt HW transforms giúp nhiều webcam mở nhanh hơn / ít treo lúc set độ phân giải
    # (phải đặt trước khi nạp OpenCV; khuyến nghị upstream / diễn đàn OpenCV).
    os.environ.setdefault("OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS", "0")
    os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_MSMF", "9999")
    os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_DSHOW", "5000")
    os.environ.setdefault("OPENCV_VIDEOIO_PRIORITY_FFMPEG", "1")
    try:
        from packrecorder.app import run_app

        raise SystemExit(run_app())
    except SystemExit:
        raise
    except Exception:
        tb = traceback.format_exc()
        log = _packrecorder_data_dir() / "crash.log"
        try:
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text(tb, encoding="utf-8")
        except OSError:
            log = Path.home() / "PackRecorder_crash.log"
            log.write_text(tb, encoding="utf-8")
        try:
            from packrecorder.session_log import (
                log_session_error,
                reset_session_log,
                session_log_path,
            )

            reset_session_log()
            et, ev, etb = sys.exc_info()
            if et is not None and etb is not None:
                log_session_error(
                    "Lỗi trước khi vào giao diện (khởi động thất bại).",
                    exc_info=(et, ev, etb),
                )
            session_file = session_log_path()
        except Exception:
            session_file = Path.cwd() / "run_errors.log"
        _show_windows_error(
            "Không khởi động được Pack Recorder.\n\n"
            f"Chi tiết: {log}\n"
            f"Log phiên (nếu có): {session_file}\n\n"
            "Gửi nội dung các file này khi báo lỗi."
        )
        raise SystemExit(1)


if __name__ == "__main__":
    import multiprocessing

    multiprocessing.freeze_support()
    main()
