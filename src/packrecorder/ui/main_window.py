from __future__ import annotations

import shutil
from datetime import date, datetime, time as time_cls
from pathlib import Path
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QMainWindow, QMessageBox, QStatusBar

from packrecorder.config import AppConfig, default_config_path, load_config, save_config
from packrecorder.duplicate import is_duplicate_order
from packrecorder.ffmpeg_pipe_recorder import FFmpegPipeRecorder
from packrecorder.feedback_sound import FeedbackPlayer
from packrecorder.order_state import OrderStateMachine, ScanResult
from packrecorder.paths import build_output_path
from packrecorder.retention import purge_old_day_folders
from packrecorder.scan_worker import ScanWorker
from packrecorder.shutdown_scheduler import compute_next_shutdown_at
from packrecorder.ui.countdown_dialog import ShutdownCountdownDialog
from packrecorder.ui.settings_dialog import SettingsDialog


def _parse_hhmm(s: str) -> time_cls:
    parts = s.replace(" ", "").split(":")
    try:
        h = int(parts[0]) if parts else 18
        m = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return time_cls(18, 0)
    return time_cls(h % 24, min(59, max(0, m)))


def _resolve_ffmpeg(cfg: AppConfig) -> Path:
    if cfg.ffmpeg_path.strip():
        p = Path(cfg.ffmpeg_path)
        if p.is_file():
            return p
    w = shutil.which("ffmpeg")
    if w:
        return Path(w)
    raise FileNotFoundError("Không tìm thấy ffmpeg. Thêm vào PATH hoặc chỉ đường dẫn trong Cài đặt.")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Pack Recorder")
        self._config_path = default_config_path()
        self._config = load_config(self._config_path)
        self._next_shutdown_at: Optional[datetime] = None
        self._next_shutdown_ref: list[Optional[datetime]] = [None]
        self._refresh_next_shutdown()
        self._order_sm = OrderStateMachine()
        self._feedback = FeedbackPlayer(self._config)
        self._recorder: Optional[FFmpegPipeRecorder] = None
        self._scan_worker: Optional[ScanWorker] = None
        self._shutdown_countdown = False
        self._countdown_dialog: Optional[ShutdownCountdownDialog] = None

        self._frame_w, self._frame_h, self._frame_fps = 640, 480, 15

        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._chip = QLabel("Chờ quét mã đơn")
        self._chip.setStyleSheet(
            "padding:6px 10px;border-radius:6px;background:#e8eaf6;color:#1a237e;"
        )
        self.statusBar().addPermanentWidget(self._chip)
        self._update_packer_message()

        act = QAction("Cài đặt", self)
        act.triggered.connect(self._open_settings)
        self.menuBar().addAction(act)

        self._purge_timer = QTimer(self)
        self._purge_timer.timeout.connect(self._run_retention)
        self._purge_timer.start(3 * 60 * 60 * 1000)
        QTimer.singleShot(0, self._run_retention)

        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.timeout.connect(self._check_shutdown)
        self._shutdown_timer.start(15_000)

        self._restart_scan_worker()

    def _update_packer_message(self) -> None:
        self._status.showMessage(f"Nhãn gói: {self._config.packer_label}", 0)

    def _refresh_next_shutdown(self) -> None:
        if not self._config.shutdown_enabled:
            self._next_shutdown_at = None
            self._next_shutdown_ref[0] = None
            return
        t = _parse_hhmm(self._config.shutdown_time_hhmm)
        self._next_shutdown_at = compute_next_shutdown_at(t, datetime.now())
        self._next_shutdown_ref[0] = self._next_shutdown_at

    def _check_shutdown(self) -> None:
        if self._shutdown_countdown:
            return
        if not self._config.shutdown_enabled or self._next_shutdown_at is None:
            return
        if datetime.now() < self._next_shutdown_at:
            return
        self._begin_shutdown_sequence()

    def _begin_shutdown_sequence(self) -> None:
        self._stop_recording_for_shutdown()
        self._shutdown_countdown = True
        dlg = ShutdownCountdownDialog(self)
        dlg.set_next_shutdown_ref(self._next_shutdown_ref)
        dlg.scan_cancelled.connect(self._on_shutdown_scan_cancelled)
        dlg.shutdown_committed.connect(self._on_shutdown_commit)
        dlg.finished.connect(self._on_countdown_finished)
        self._countdown_dialog = dlg
        dlg.setModal(False)
        dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        dlg.start_countdown()
        dlg.show()

    def _on_countdown_finished(self) -> None:
        self._countdown_dialog = None
        self._shutdown_countdown = False

    def _on_shutdown_scan_cancelled(self) -> None:
        self._next_shutdown_at = self._next_shutdown_ref[0]
        self._shutdown_countdown = False
        self._status.showMessage("Đã hoãn tắt máy +1 giờ (quét mã).", 8000)

    def _on_shutdown_commit(self) -> None:
        self._cleanup_workers()

    def _run_retention(self) -> None:
        root = Path(self._config.video_root)
        if not root.is_dir():
            return
        purge_old_day_folders(root, 16, date.today())

    def _restart_scan_worker(self) -> None:
        if self._scan_worker:
            self._scan_worker.stop_worker()
            self._scan_worker.wait(5000)
        sw = ScanWorker(
            self._config.camera_index,
            is_shutdown_countdown=lambda: self._shutdown_countdown,
        )
        sw.decoded.connect(self._on_decoded)
        sw.frame_ready.connect(self._on_frame)
        sw.camera_opened.connect(self._on_camera_dims)
        sw.start()
        self._scan_worker = sw

    def _on_camera_dims(self, w: int, h: int, fps: int) -> None:
        self._frame_w, self._frame_h, self._frame_fps = w, h, max(1, min(60, fps or 15))

    def _on_frame(self, bgr: bytes) -> None:
        if self._recorder:
            try:
                self._recorder.write_frame(bgr)
            except BrokenPipeError:
                pass

    def _on_decoded(self, code: str) -> None:
        if self._shutdown_countdown and self._countdown_dialog is not None:
            self._countdown_dialog.on_barcode_during_countdown()
            return
        r = self._order_sm.on_scan(code, is_shutdown_countdown=False)
        if r.should_start_recording and r.new_active_order:
            self._begin_recording(r.new_active_order, check_dup=r.should_check_duplicate)
        if r.should_stop_recording:
            self._stop_recording_after_scan(r)

    def _begin_recording(self, order: str, *, check_dup: bool) -> None:
        root = Path(self._config.video_root)
        root.mkdir(parents=True, exist_ok=True)
        dup = False
        if check_dup:
            dup = is_duplicate_order(root, order, date.today())
            if dup:
                self._status.showMessage(
                    f"Đơn {order} đã có video hôm nay — vẫn ghi thêm.", 8000
                )
        try:
            ff = _resolve_ffmpeg(self._config)
        except FileNotFoundError as e:
            QMessageBox.warning(self, "Thiếu ffmpeg", str(e))
            self._order_sm = OrderStateMachine()
            return
        out = build_output_path(
            root, order, self._config.packer_label, datetime.now()
        )
        self._recorder = FFmpegPipeRecorder(
            ff, self._frame_w, self._frame_h, self._frame_fps
        )
        try:
            self._recorder.start(out)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Không bắt đầu ghi được", str(e))
            self._recorder = None
            self._order_sm = OrderStateMachine()
            return
        if self._scan_worker:
            self._scan_worker.set_recording(True)
        self._chip.setText(f"Đang ghi: {order}")
        self._chip.setStyleSheet(
            "padding:6px 10px;border-radius:6px;background:#c8e6c9;color:#1b5e20;"
        )
        if dup:
            self._feedback.play_long()
        else:
            self._feedback.play_short()

    def _stop_recording_for_shutdown(self) -> None:
        if self._scan_worker:
            self._scan_worker.set_recording(False)
        if self._recorder:
            try:
                self._recorder.stop()
            except Exception:
                pass
            self._recorder = None
        self._chip.setText("Chờ quét mã đơn")
        self._chip.setStyleSheet(
            "padding:6px 10px;border-radius:6px;background:#e8eaf6;color:#1a237e;"
        )

    def _stop_recording_after_scan(self, r: ScanResult) -> None:
        if self._scan_worker:
            self._scan_worker.set_recording(False)
        if self._recorder:
            try:
                self._recorder.stop()
            except Exception:
                pass
            self._recorder = None
        if r.sound_immediate == "stop_double":
            self._feedback.play_double()
        nr = self._order_sm.notify_stop_confirmed()
        if nr.should_start_recording and nr.new_active_order:
            self._begin_recording(
                nr.new_active_order, check_dup=nr.should_check_duplicate
            )
        else:
            self._chip.setText("Chờ quét mã đơn")
            self._chip.setStyleSheet(
                "padding:6px 10px;border-radius:6px;background:#e8eaf6;color:#1a237e;"
            )

    def _open_settings(self) -> None:
        dlg = SettingsDialog(self._config, self)
        if dlg.exec():
            self._config = dlg.result_config()
            save_config(self._config_path, self._config)
            self._feedback.update_config(self._config)
            self._refresh_next_shutdown()
            self._restart_scan_worker()
            self._update_packer_message()

    def _cleanup_workers(self) -> None:
        if self._scan_worker:
            self._scan_worker.stop_worker()
            self._scan_worker.wait(5000)
            self._scan_worker = None
        self._stop_recording_for_shutdown()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._cleanup_workers()
        super().closeEvent(event)
