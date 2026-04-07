from __future__ import annotations

import time
from datetime import date, datetime, time as time_cls
from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtCore import QEvent, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QDesktopServices, QShowEvent
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
)

from packrecorder.config import (
    AppConfig,
    StationConfig,
    camera_should_decode_on_index,
    default_config_path,
    ensure_dual_stations,
    load_config,
    normalize_config,
    save_config,
    station_for_decode_camera,
    station_uses_serial_scanner,
)
from packrecorder.duplicate import is_duplicate_order
from packrecorder.ffmpeg_locate import resolve_ffmpeg as _resolve_ffmpeg
from packrecorder.ffmpeg_pipe_recorder import FFmpegPipeRecorder
from packrecorder.feedback_sound import FeedbackPlayer
from packrecorder.order_input import normalize_manual_order_text
from packrecorder.order_state import OrderStateMachine, ScanResult
from packrecorder.paths import build_output_path
from packrecorder.pip_composite import composite_pip_bgr
from packrecorder.retention import purge_old_day_folders
from packrecorder.session_log import log_session_error, mark_session_phase, session_log_path
from packrecorder.scan_worker import ScanWorker
from packrecorder.serial_scan_worker import SerialScanWorker
from packrecorder.shutdown_scheduler import compute_next_shutdown_at
from packrecorder.ui.camera_preview import bgr_bytes_to_pixmap
from packrecorder.ui.countdown_dialog import ShutdownCountdownDialog
from packrecorder.ui.dual_station_widget import DualStationWidget
from packrecorder.ui.settings_dialog import SettingsDialog
from packrecorder.video_overlay import (
    RecordingBurnIn,
    burn_in_recording_info_bgr,
    format_elapsed_overlay,
)


def _parse_hhmm(s: str) -> time_cls:
    parts = s.replace(" ", "").split(":")
    try:
        h = int(parts[0]) if parts else 18
        m = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return time_cls(18, 0)
    return time_cls(h % 24, min(59, max(0, m)))


_CHIP_IDLE_STYLE = (
    "padding:6px 10px;border-radius:6px;background:#e8eaf6;color:#1a237e;"
)
_CHIP_REC_STYLE = (
    "padding:6px 10px;border-radius:6px;background:#c8e6c9;color:#1b5e20;"
)
_REC_ELAPSED_BAR_STYLE = (
    "padding:6px 12px;border-radius:6px;background-color:#ffebee;color:#b71c1c;"
    "font-size:16px;font-weight:bold;font-family:Consolas,'Cascadia Mono',monospace;"
    "border:2px solid #c62828;"
)
_MANUAL_ORDER_DEBOUNCE_S = 0.45
_DEFAULT_RECORDING_FPS = 30


def _format_recording_elapsed(since: datetime) -> str:
    return format_elapsed_overlay(since, datetime.now())


def _ms_until_next_wall_second() -> int:
    """Milliseconds tới mốc giây đầy đủ tiếp theo của đồng hồ hệ thống (đồng bộ nhảy số)."""
    t = time.time()
    nxt = int(t) + 1
    ms = int((nxt - t) * 1000)
    return max(1, min(ms, 1000))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Pack Recorder")
        self._config_path = default_config_path()
        self._config = load_config(self._config_path)
        ensure_dual_stations(self._config)
        self._config = normalize_config(self._config)
        save_config(self._config_path, self._config)
        self._next_shutdown_at: Optional[datetime] = None
        self._next_shutdown_ref: list[Optional[datetime]] = [None]
        self._refresh_next_shutdown()
        self._feedback = FeedbackPlayer(self._config)
        self._shutdown_countdown = False
        self._countdown_dialog: Optional[ShutdownCountdownDialog] = None

        self._workers: dict[int, ScanWorker] = {}
        self._serial_workers: dict[str, SerialScanWorker] = {}
        self._preview_route: dict[int, int] = {}
        self._pip_wh: dict[int, tuple[int, int]] = {}
        self._camera_fps: dict[int, int] = {}
        self._pip_last_frame: dict[int, bytes] = {}
        self._frame_w, self._frame_h, self._frame_fps = (
            640,
            480,
            _DEFAULT_RECORDING_FPS,
        )
        self._manual_submit_debounce: dict[int, tuple[str, float]] = {}
        self._serial_submit_debounce: dict[str, tuple[str, float]] = {}

        self._order_sm: dict[str, OrderStateMachine] = {}
        self._recorders: dict[str, FFmpegPipeRecorder | None] = {}
        self._station_recording_order: dict[str, str] = {}
        self._recording_started_at: dict[str, datetime] = {}
        self._camera_probe_busy = False
        self._pip_timer = QTimer(self)
        self._pip_timer.timeout.connect(self._pip_tick)
        self._rec_elapsed_timer = QTimer(self)
        self._rec_elapsed_timer.setInterval(1000)
        self._rec_elapsed_timer.timeout.connect(self._on_rec_elapsed_timer)
        self._rec_elapsed_resync_wall_second = True
        self._record_pace_timer = QTimer(self)
        self._record_pace_timer.setInterval(10)
        self._record_pace_timer.timeout.connect(self._recording_emit_tick)
        self._latest_record_bgr: dict[str, bytes] = {}
        self._recording_next_emit_mono: dict[str, float] = {}
        self._recording_emit_fps: dict[str, int] = {}
        self._recording_frame_wh: dict[str, tuple[int, int]] = {}
        self._recording_burnin: dict[str, RecordingBurnIn] = {}

        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._rec_elapsed_bar = QLabel("")
        self._rec_elapsed_bar.setVisible(False)
        self._rec_elapsed_bar.setStyleSheet(_REC_ELAPSED_BAR_STYLE)
        self.statusBar().addPermanentWidget(self._rec_elapsed_bar)
        self._chip = QLabel("Chờ quét mã đơn")
        self._chip.setStyleSheet(_CHIP_IDLE_STYLE)
        self.statusBar().addPermanentWidget(self._chip)

        self._stack = QStackedWidget()
        self._dual_panel = DualStationWidget()
        self._dual_panel.fields_changed.connect(self._on_dual_fields_changed)
        self._dual_panel.refresh_devices_requested.connect(self._on_dual_refresh_devices)
        self._dual_panel.manual_order_submitted.connect(self._on_manual_order_submitted)
        self._mode_hint = QLabel(
            "Chế độ hiện tại không phải «Đa quầy». Vào Tệp → Cài đặt → chọn "
            "«Đa quầy — mỗi camera + tên + quét (tuỳ chọn 1)» để dùng màn hình 2 cột."
        )
        self._mode_hint.setWordWrap(True)
        self._mode_hint.setStyleSheet("padding:24px;color:#555;")
        self._stack.addWidget(self._dual_panel)
        self._stack.addWidget(self._mode_hint)
        self._update_central_page()
        self.setCentralWidget(self._stack)
        self.setMinimumSize(920, 560)
        self.resize(1040, 640)

        self._rebuild_order_machines()
        self._update_packer_message()

        m_settings = self.menuBar().addMenu("Tệp")
        act = QAction("Cài đặt", self)
        act.triggered.connect(self._open_settings)
        m_settings.addAction(act)
        act_log = QAction("Mở thư mục log lỗi…", self)
        act_log.setToolTip(
            "run_errors.log trong thư mục hiện tại (folder chạy lệnh / cùng chỗ file exe) — "
            "mỗi lần khởi động app ghi lại từ đầu."
        )
        act_log.triggered.connect(self._open_error_log_folder)
        m_settings.addAction(act_log)

        self._purge_timer = QTimer(self)
        self._purge_timer.timeout.connect(self._run_retention)
        self._purge_timer.start(3 * 60 * 60 * 1000)
        QTimer.singleShot(0, self._run_retention)

        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.timeout.connect(self._check_shutdown)
        self._shutdown_timer.start(15_000)

    def _update_central_page(self) -> None:
        if self._config.multi_camera_mode == "stations":
            ensure_dual_stations(self._config)
            self._stack.setCurrentWidget(self._dual_panel)
            self._dual_panel.sync_from_config(
                self._config, probed_override=[], fast_serial_scan=True
            )
            QTimer.singleShot(0, self._deferred_stations_scan_and_probe)
        else:
            self._stack.setCurrentWidget(self._mode_hint)
            QTimer.singleShot(0, self._restart_scan_workers)

    def _deferred_stations_scan_and_probe(self) -> None:
        if self._config.multi_camera_mode != "stations":
            return
        try:
            self._restart_scan_workers()
            # Hoãn probe nền để worker mở camera xong trước — tránh xung đột driver (MSMF) gây crash/tắt app.
            QTimer.singleShot(800, self.start_background_camera_probe)
        except Exception:
            import sys

            log_session_error(
                "Lỗi khi khởi động worker/probe camera (đa quầy).",
                exc_info=sys.exc_info(),
            )

    def _camera_indices_for_probe_skip(self) -> set[int]:
        """Index không mở lại khi probe nền (worker/UI đang dùng)."""
        return self._required_camera_indices() | self._dual_panel.camera_indices_selected_in_ui()

    def start_background_camera_probe(self) -> None:
        if self._config.multi_camera_mode != "stations":
            return
        if self._camera_probe_busy:
            return
        from packrecorder.camera_probe_thread import CameraProbeThread

        self._camera_probe_busy = True
        self._dual_panel.set_refresh_busy(True)
        th = CameraProbeThread(
            self, skip_open_for_indices=self._camera_indices_for_probe_skip()
        )
        th.indices_ready.connect(self._on_initial_camera_probe_finished)
        th.finished.connect(self._on_camera_probe_thread_cleanup)
        th.start()

    def _on_camera_probe_thread_cleanup(self) -> None:
        self._camera_probe_busy = False
        self._dual_panel.set_refresh_busy(False)

    def _on_dual_refresh_devices(self) -> None:
        if self._config.multi_camera_mode != "stations":
            return
        if self._camera_probe_busy:
            return
        from packrecorder.camera_probe_thread import CameraProbeThread

        self._camera_probe_busy = True
        self._dual_panel.set_refresh_busy(True)
        th = CameraProbeThread(
            self, skip_open_for_indices=self._camera_indices_for_probe_skip()
        )
        th.indices_ready.connect(self._on_refresh_camera_probe_finished)
        th.finished.connect(self._on_camera_probe_thread_cleanup)
        th.start()

    def _on_initial_camera_probe_finished(self, found: list) -> None:
        if self._config.multi_camera_mode == "stations":
            self._dual_panel.sync_from_config(
                self._config, probed_override=found, fast_serial_scan=True
            )

    def _on_refresh_camera_probe_finished(self, found: list) -> None:
        if self._config.multi_camera_mode == "stations":
            self._dual_panel.apply_camera_probe_result(found)

    def _on_dual_fields_changed(self) -> None:
        if self._config.multi_camera_mode != "stations":
            return
        if self._dual_panel.duplicate_scanner_ports():
            QMessageBox.warning(
                self,
                "Trùng cổng máy quét",
                "Hai máy không thể dùng chung một cổng COM.\n"
                "Chọn cổng khác cho một trong hai cột.",
            )
            return
        if self._dual_panel.has_decode_on_peer_record_collision():
            QMessageBox.warning(
                self,
                "Camera đọc mã trùng camera ghi quầy khác",
                "Một quầy đang chọn «Camera đọc mã» trùng với «Camera ghi» của quầy còn lại.\n\n"
                "Khi quầy kia quét bằng COM, camera ghi của họ vẫn bật đọc mã trên hình — "
                "mã có thể bị gán nhầm sang quầy này và tự bắt đầu ghi.\n\n"
                "Hãy đặt «Camera đọc mã» = camera nhìn đúng khu quét của quầy này "
                "(thường là cùng camera với «Camera ghi» của chính quầy đó).",
            )
            return
        if self._dual_panel.has_decode_camera_collision():
            QMessageBox.warning(
                self,
                "Trùng camera đọc mã",
                "Hai quầy đang cùng «Camera đọc mã» và không dùng máy quét COM.\n"
                "Mã quét từ camera chỉ được gán một quầy — hãy đổi camera đọc mã hoặc dùng COM riêng.",
            )
            return
        self._dual_panel.apply_to_config(self._config)
        self._config = normalize_config(self._config)
        save_config(self._config_path, self._config)
        self._rebuild_order_machines()
        self._update_packer_message()
        self._restart_scan_workers()

    def _on_worker_preview(self, cam_idx: int, bgr: bytes) -> None:
        if self._config.multi_camera_mode != "stations":
            return
        col = self._preview_route.get(cam_idx)
        if col is None:
            return
        wh = self._pip_wh.get(cam_idx)
        if not wh:
            return
        w, h = wh
        max_px = self._dual_panel.preview_max_scale_px(col)
        pix = bgr_bytes_to_pixmap(
            bgr, w, h, max_w=max_px, fast_scale=self._dual_panel.preview_uses_fast_scale()
        )
        if pix is None:
            return
        self._dual_panel.set_preview_column(col, pix)

    def _on_serial_decoded(self, station_id: str, text: str) -> None:
        if self._shutdown_countdown and self._countdown_dialog is not None:
            return
        text = normalize_manual_order_text(text)
        if not text:
            return
        # Chỉ debounce khi không đang ghi: wedge/COM có thể gửi trùng nhanh khi chờ đơn.
        # Khi đang ghi, quét lại cùng mã phải tới state machine để dừng — không được chặn.
        now = time.monotonic()
        if not self._recorders.get(station_id):
            last = self._serial_submit_debounce.get(station_id)
            if (
                last
                and last[0] == text
                and (now - last[1]) < _MANUAL_ORDER_DEBOUNCE_S
            ):
                return
        self._serial_submit_debounce[station_id] = (text, now)
        st = self._station_by_id(station_id)
        if st is not None:
            short = text if len(text) <= 64 else text[:61] + "…"
            self._status.showMessage(
                f"[{st.packer_label}] Máy quét COM: {short}",
                5000,
            )
        self._handle_decode_station(station_id, text)

    def _on_serial_failed(self, station_id: str, message: str) -> None:
        st = self._station_by_id(station_id)
        lab = st.packer_label if st else station_id
        self._status.showMessage(f"[{lab}] Máy quét serial: {message}", 12000)

    def _effective_stations(self) -> list[StationConfig]:
        if self._config.multi_camera_mode == "single":
            return [
                StationConfig(
                    "single",
                    self._config.packer_label,
                    self._config.camera_index,
                    self._config.camera_index,
                )
            ]
        if self._config.multi_camera_mode == "pip":
            return [
                StationConfig(
                    "pip",
                    self._config.packer_label,
                    self._config.pip_main_camera_index,
                    self._config.pip_decode_camera_index,
                )
            ]
        return list(self._config.stations)

    def _rebuild_order_machines(self) -> None:
        self._order_sm = {
            s.station_id: OrderStateMachine() for s in self._effective_stations()
        }
        self._recorders = {s.station_id: None for s in self._effective_stations()}

    def _update_packer_message(self) -> None:
        hint = "Quét mã đơn → bắt đầu ghi; quét lại cùng mã → dừng."
        if self._config.multi_camera_mode == "stations":
            names = ", ".join(s.packer_label for s in self._config.stations)
            self._status.showMessage(f"Quầy: {names}. {hint}", 0)
        elif self._config.multi_camera_mode == "pip":
            self._status.showMessage(
                f"PIP — nhãn: {self._config.packer_label} "
                f"(chính cam {self._config.pip_main_camera_index}, "
                f"phụ cam {self._config.pip_sub_camera_index}). {hint}",
                0,
            )
        else:
            self._status.showMessage(
                f"Nhãn gói: {self._config.packer_label}. {hint}",
                0,
            )

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
        self._stop_all_recording_for_shutdown()
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

    def _required_camera_indices(self) -> set[int]:
        if self._config.multi_camera_mode == "single":
            return {self._config.camera_index}
        if self._config.multi_camera_mode == "pip":
            return {
                self._config.pip_main_camera_index,
                self._config.pip_sub_camera_index,
            }
        cams: set[int] = set()
        for st in self._config.stations:
            cams.add(st.record_camera_index)
            if not station_uses_serial_scanner(st):
                cams.add(st.decode_camera_index)
        return cams

    def _camera_should_decode(self, cam: int) -> bool:
        if self._config.multi_camera_mode == "single":
            return True
        if self._config.multi_camera_mode == "pip":
            return cam == self._config.pip_decode_camera_index
        return camera_should_decode_on_index(self._config.stations, cam)

    def _stop_serial_workers(self) -> None:
        for w in self._serial_workers.values():
            w.stop_worker()
        for w in self._serial_workers.values():
            w.wait(3000)
        self._serial_workers.clear()

    def _restart_scan_workers(self) -> None:
        self._pip_timer.stop()
        self._stop_serial_workers()
        for w in self._workers.values():
            w.stop_worker()
        for w in self._workers.values():
            w.wait(5000)
        self._workers.clear()
        self._camera_fps.clear()
        self._manual_submit_debounce.clear()
        self._serial_submit_debounce.clear()
        self._pip_last_frame.clear()
        self._preview_route.clear()
        if self._config.multi_camera_mode == "stations":
            self._dual_panel.clear_previews()
            for col, st in enumerate(self._config.stations[:2]):
                self._preview_route[st.record_camera_index] = col

        is_sd = lambda: self._shutdown_countdown
        for cam in sorted(self._required_camera_indices()):
            decode = self._camera_should_decode(cam)
            w = ScanWorker(
                cam,
                decode_enabled=decode,
                is_shutdown_countdown=is_sd,
                preview_fps=24.0 if self._config.multi_camera_mode == "stations" else 0.0,
            )
            w.decoded.connect(self._on_decoded)
            w.frame_ready.connect(self._on_frame)
            w.camera_opened.connect(self._on_camera_opened_slot)
            if self._config.multi_camera_mode == "stations":
                w.preview_ready.connect(self._on_worker_preview)
            w.start()
            self._workers[cam] = w

        if self._config.multi_camera_mode == "stations":
            for st in self._config.stations:
                if not station_uses_serial_scanner(st):
                    continue
                port = st.scanner_serial_port.strip()
                if not port:
                    continue
                sw = SerialScanWorker(
                    st.station_id,
                    port,
                    baudrate=st.scanner_serial_baud,
                )
                sw.line_decoded.connect(self._on_serial_decoded)
                sw.failed.connect(self._on_serial_failed)
                sw.start()
                self._serial_workers[st.station_id] = sw

    def _on_camera_opened_slot(self, cam: int, w: int, h: int, fps: int) -> None:
        self._pip_wh[cam] = (w, h)
        fps = max(1, min(60, fps or _DEFAULT_RECORDING_FPS))
        self._camera_fps[cam] = fps
        if self._config.multi_camera_mode == "single" and cam == self._config.camera_index:
            self._frame_w, self._frame_h, self._frame_fps = w, h, fps
        elif (
            self._config.multi_camera_mode == "pip"
            and cam == self._config.pip_main_camera_index
        ):
            self._frame_w, self._frame_h, self._frame_fps = w, h, fps

    def _station_by_id(self, sid: str) -> StationConfig | None:
        for s in self._effective_stations():
            if s.station_id == sid:
                return s
        return None

    def _station_column(self, station_id: str) -> int | None:
        if self._config.multi_camera_mode != "stations":
            return None
        for i, s in enumerate(self._config.stations[:2]):
            if s.station_id == station_id:
                return i
        return None

    def _recording_banner_text(self, st: StationConfig, order: str) -> str:
        short_order = order if len(order) <= 48 else order[:45] + "…"
        rec_cam = st.record_camera_index
        if station_uses_serial_scanner(st):
            port = (st.scanner_serial_port or "").strip()
            src = f"máy quét USB ({port})" if port else "máy quét USB"
        else:
            src = f"camera đọc mã {st.decode_camera_index}"
        return (
            f"ĐANG GHI HÌNH — {st.packer_label}\n"
            f"Đơn: {short_order}\n"
            f"Đang quay: camera {rec_cam}  ·  Quét từ: {src}"
        )

    def _sync_stations_recording_chip(self) -> None:
        if self._config.multi_camera_mode != "stations":
            return
        active = [
            st
            for st in self._config.stations[:2]
            if self._recorders.get(st.station_id)
        ]
        if not active:
            self._chip.setText("Chờ quét mã đơn")
            self._chip.setStyleSheet(_CHIP_IDLE_STYLE)
            return
        parts: list[str] = []
        for st in active:
            oid = self._station_recording_order.get(st.station_id, "")
            if oid:
                short = oid if len(oid) <= 28 else oid[:25] + "…"
                parts.append(f"{st.packer_label}: {short}")
            else:
                parts.append(st.packer_label)
        self._chip.setText("Đang ghi — " + "  |  ".join(parts))
        self._chip.setStyleSheet(_CHIP_REC_STYLE)

    def _any_active_recorder(self) -> bool:
        return any(r is not None for r in self._recorders.values())

    def _sync_recording_elapsed_timer(self) -> None:
        if not self._any_active_recorder():
            self._rec_elapsed_timer.stop()
            self._rec_elapsed_resync_wall_second = True
            if self._rec_elapsed_bar.isVisible() or self._rec_elapsed_bar.text():
                self._rec_elapsed_bar.clear()
                self._rec_elapsed_bar.setVisible(False)
            if self._config.multi_camera_mode == "stations":
                self._dual_panel.clear_recording_timers()
            return
        if not self._rec_elapsed_timer.isActive():
            self._rec_elapsed_resync_wall_second = True
            self._rec_elapsed_timer.setInterval(_ms_until_next_wall_second())
            self._rec_elapsed_timer.start()
        self._tick_recording_elapsed()

    def _on_rec_elapsed_timer(self) -> None:
        self._tick_recording_elapsed()
        if self._rec_elapsed_resync_wall_second:
            self._rec_elapsed_resync_wall_second = False
            self._rec_elapsed_timer.stop()
            self._rec_elapsed_timer.setInterval(1000)
            self._rec_elapsed_timer.start()

    def _tick_recording_elapsed(self) -> None:
        if not self._any_active_recorder():
            return
        bar = self._rec_elapsed_bar
        if self._config.multi_camera_mode == "stations":
            if bar.isVisible():
                bar.setVisible(False)
            for col, st in enumerate(self._config.stations[:2]):
                sid = st.station_id
                if self._recorders.get(sid):
                    t0 = self._recording_started_at.get(sid)
                    if t0:
                        el = _format_recording_elapsed(t0)
                        self._dual_panel.set_column_recording_timer(
                            col, f"● ĐANG QUAY  {el}"
                        )
                else:
                    self._dual_panel.set_column_recording_timer(col, None)
        elif self._config.multi_camera_mode == "pip":
            if self._recorders.get("pip") and self._recording_started_at.get("pip"):
                el = _format_recording_elapsed(self._recording_started_at["pip"])
                order = self._station_recording_order.get("pip", "")
                short = order if len(order) <= 22 else order[:19] + "…"
                new_txt = f"● ĐANG QUAY  {el}  ·  Đơn: {short}"
                if bar.text() != new_txt:
                    bar.setText(new_txt)
                if not bar.isVisible():
                    bar.setStyleSheet(_REC_ELAPSED_BAR_STYLE)
                    bar.setVisible(True)
            elif bar.isVisible():
                bar.setVisible(False)
        else:
            if self._recorders.get("single") and self._recording_started_at.get("single"):
                el = _format_recording_elapsed(self._recording_started_at["single"])
                order = self._station_recording_order.get("single", "")
                short = order if len(order) <= 22 else order[:19] + "…"
                new_txt = f"● ĐANG QUAY  {el}  ·  Đơn: {short}"
                if bar.text() != new_txt:
                    bar.setText(new_txt)
                if not bar.isVisible():
                    bar.setStyleSheet(_REC_ELAPSED_BAR_STYLE)
                    bar.setVisible(True)
            elif bar.isVisible():
                bar.setVisible(False)

    def _reshape_bgr(self, cam: int, raw: bytes) -> np.ndarray | None:
        wh = self._pip_wh.get(cam)
        if not wh:
            return None
        w, h = wh
        need = w * h * 3
        if len(raw) != need:
            return None
        return np.frombuffer(raw, dtype=np.uint8).reshape((h, w, 3))

    def _pip_tick(self) -> None:
        if self._config.multi_camera_mode != "pip" or not self._recorders.get("pip"):
            return
        mc = self._config.pip_main_camera_index
        sc = self._config.pip_sub_camera_index
        b1 = self._pip_last_frame.get(mc)
        b2 = self._pip_last_frame.get(sc)
        if not b1 or not b2:
            return
        a = self._reshape_bgr(mc, b1)
        b = self._reshape_bgr(sc, b2)
        if a is None or b is None:
            return
        out = composite_pip_bgr(
            a,
            b,
            sub_max_width=self._config.pip_overlay_max_width,
            margin=self._config.pip_overlay_margin,
        )
        rec = self._recorders.get("pip")
        if rec:
            try:
                ctx = self._recording_burnin.get("pip")
                if ctx is not None:
                    wall_now = datetime.now()
                    out = burn_in_recording_info_bgr(
                        out,
                        order=ctx.order,
                        packer=ctx.packer,
                        wall_now=wall_now,
                        started_at=ctx.started_at,
                    )
                rec.write_frame(out.tobytes())
            except BrokenPipeError:
                pass

    def _clear_recording_pace_state(self, station_id: str) -> None:
        self._latest_record_bgr.pop(station_id, None)
        self._recording_next_emit_mono.pop(station_id, None)
        self._recording_emit_fps.pop(station_id, None)
        self._recording_frame_wh.pop(station_id, None)
        self._recording_burnin.pop(station_id, None)

    def _ensure_record_pace_timer(self) -> None:
        if not self._record_pace_timer.isActive():
            self._record_pace_timer.start()

    def _maybe_stop_record_pace_timer(self) -> None:
        if not any(v is not None for v in self._recorders.values()):
            self._record_pace_timer.stop()

    def _recording_emit_tick(self) -> None:
        """Ghi đúng fps theo đồng hồ tường (lặp khung cuối nếu camera chậm) để độ dài file khớp thời gian quay."""
        now = time.monotonic()
        max_burst = 10
        for sid, rec in list(self._recorders.items()):
            if rec is None or sid == "pip":
                continue
            nxt = self._recording_next_emit_mono.get(sid)
            if nxt is None:
                continue
            fps = max(1, self._recording_emit_fps.get(sid, _DEFAULT_RECORDING_FPS))
            interval = 1.0 / fps
            raw = self._latest_record_bgr.get(sid)
            wh = self._recording_frame_wh.get(sid)
            ctx = self._recording_burnin.get(sid)
            if wh is None or ctx is None:
                continue
            w, h = wh
            need = w * h * 3
            burst = 0
            while now >= nxt and burst < max_burst:
                if raw is not None and len(raw) == need:
                    frame_arr = np.frombuffer(
                        memoryview(raw), dtype=np.uint8
                    ).reshape((h, w, 3))
                else:
                    frame_arr = np.zeros((h, w, 3), dtype=np.uint8)
                wall_now = datetime.now()
                out = burn_in_recording_info_bgr(
                    frame_arr,
                    order=ctx.order,
                    packer=ctx.packer,
                    wall_now=wall_now,
                    started_at=ctx.started_at,
                )
                try:
                    rec.write_frame(out.tobytes())
                except BrokenPipeError:
                    break
                nxt += interval
                burst += 1
            self._recording_next_emit_mono[sid] = nxt

    def _on_frame(self, cam_idx: int, bgr: bytes) -> None:
        if self._config.multi_camera_mode == "pip":
            if self._recorders.get("pip"):
                self._pip_last_frame[cam_idx] = bgr
            return
        if self._config.multi_camera_mode == "single":
            if self._recorders.get("single") and cam_idx == self._config.camera_index:
                self._latest_record_bgr["single"] = bgr
            return
        for st in self._config.stations:
            if (
                self._recorders.get(st.station_id)
                and cam_idx == st.record_camera_index
            ):
                self._latest_record_bgr[st.station_id] = bgr

    def _refresh_worker_recording_flags(self) -> None:
        active_record_cams: set[int] = set()
        if self._config.multi_camera_mode == "pip":
            if self._recorders.get("pip"):
                active_record_cams.add(self._config.pip_main_camera_index)
                active_record_cams.add(self._config.pip_sub_camera_index)
        elif self._config.multi_camera_mode == "single":
            if self._recorders.get("single"):
                active_record_cams.add(self._config.camera_index)
        else:
            for st in self._config.stations:
                if self._recorders.get(st.station_id):
                    active_record_cams.add(st.record_camera_index)
        for cam, w in self._workers.items():
            w.set_recording(cam in active_record_cams)

    def _on_decoded(self, cam_idx: int, code: str) -> None:
        if self._shutdown_countdown and self._countdown_dialog is not None:
            self._countdown_dialog.on_barcode_during_countdown()
            return
        if self._config.multi_camera_mode == "pip":
            self._handle_decode_pip(code)
            return
        if self._config.multi_camera_mode == "single":
            if cam_idx != self._config.camera_index:
                return
            self._handle_decode_station("single", code)
            return

        st = station_for_decode_camera(self._config.stations, cam_idx)
        if st is None:
            self._status.showMessage(
                f"Không có quầy nào gán camera {cam_idx} làm «Camera đọc mã» — chỉnh trong cột Máy.",
                6000,
            )
            return
        short = code if len(code) <= 64 else code[:61] + "…"
        self._status.showMessage(
            f"[{st.packer_label}] Quét camera {cam_idx}: {short}",
            5000,
        )
        self._handle_decode_station(st.station_id, code)

    def _on_manual_order_submitted(self, col: int, text: str) -> None:
        if self._shutdown_countdown and self._countdown_dialog is not None:
            return
        if self._config.multi_camera_mode != "stations":
            return
        if not (0 <= col < len(self._config.stations)):
            return
        text = normalize_manual_order_text(text)
        if not text:
            return
        sid = self._config.stations[col].station_id
        now = time.monotonic()
        if not self._recorders.get(sid):
            last = self._manual_submit_debounce.get(col)
            if (
                last
                and last[0] == text
                and (now - last[1]) < _MANUAL_ORDER_DEBOUNCE_S
            ):
                return
        self._manual_submit_debounce[col] = (text, now)
        st = self._config.stations[col]
        short = text if len(text) <= 64 else text[:61] + "…"
        self._status.showMessage(f"[{st.packer_label}] Nhập tay: {short}", 5000)
        self._handle_decode_station(sid, text)
        self._dual_panel.clear_manual_order_column(col)

    def _handle_decode_pip(self, code: str) -> None:
        code = normalize_manual_order_text(code)
        if not code:
            return
        sm = self._order_sm["pip"]
        r = sm.on_scan(code, is_shutdown_countdown=False)
        if r.should_start_recording and r.new_active_order:
            self._begin_recording_pip(
                r.new_active_order, check_dup=r.should_check_duplicate
            )
        if r.should_stop_recording:
            self._stop_recording_after_scan("pip", r)

    def _handle_decode_station(self, station_id: str, code: str) -> None:
        code = normalize_manual_order_text(code)
        if not code:
            return
        sm = self._order_sm.get(station_id)
        if sm is None:
            return
        r = sm.on_scan(code, is_shutdown_countdown=False)
        if r.should_start_recording and r.new_active_order:
            self._begin_recording_station(
                station_id,
                r.new_active_order,
                check_dup=r.should_check_duplicate,
            )
        if r.should_stop_recording:
            self._stop_recording_after_scan(station_id, r)

    def _begin_recording_station(
        self, station_id: str, order: str, *, check_dup: bool
    ) -> None:
        st = self._station_by_id(station_id)
        if st is None:
            return
        root = Path(self._config.video_root)
        root.mkdir(parents=True, exist_ok=True)
        dup = False
        if check_dup:
            dup = is_duplicate_order(root, order, date.today())
            if dup:
                self._status.showMessage(
                    f"[{st.packer_label}] Đơn {order} đã có video hôm nay — vẫn ghi thêm.",
                    8000,
                )
        try:
            ff = _resolve_ffmpeg(self._config)
        except FileNotFoundError:
            self._show_ffmpeg_missing_dialog()
            self._order_sm[station_id] = OrderStateMachine()
            return
        w, h = self._pip_wh.get(st.record_camera_index, (self._frame_w, self._frame_h))
        fps = self._camera_fps.get(st.record_camera_index, self._frame_fps)
        out = build_output_path(
            root, order, st.packer_label, datetime.now()
        )
        rec = FFmpegPipeRecorder(ff, w, h, fps)
        try:
            rec.start(out)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Không bắt đầu ghi được", str(e))
            self._order_sm[station_id] = OrderStateMachine()
            return
        self._recorders[station_id] = rec
        self._recording_started_at[station_id] = datetime.now()
        t0 = self._recording_started_at[station_id]
        self._recording_burnin[station_id] = RecordingBurnIn(
            order, st.packer_label, t0
        )
        self._recording_frame_wh[station_id] = (w, h)
        self._recording_emit_fps[station_id] = fps
        self._recording_next_emit_mono[station_id] = time.monotonic()
        self._latest_record_bgr.pop(station_id, None)
        self._ensure_record_pace_timer()
        self._refresh_worker_recording_flags()
        if self._config.multi_camera_mode == "stations":
            self._station_recording_order[station_id] = order
            col = self._station_column(station_id)
            if col is not None:
                self._dual_panel.set_column_recording_banner(
                    col, self._recording_banner_text(st, order)
                )
            self._sync_stations_recording_chip()
        else:
            self._station_recording_order[station_id] = order
            self._chip.setText(f"Đang ghi ({st.packer_label}): {order}")
            self._chip.setStyleSheet(_CHIP_REC_STYLE)
        self._sync_recording_elapsed_timer()
        if dup:
            self._feedback.play_quad()
        else:
            self._feedback.play_short()

    def _begin_recording_pip(self, order: str, *, check_dup: bool) -> None:
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
        except FileNotFoundError:
            self._show_ffmpeg_missing_dialog()
            self._order_sm["pip"] = OrderStateMachine()
            return
        out = build_output_path(
            root, order, self._config.packer_label, datetime.now()
        )
        mc = self._config.pip_main_camera_index
        fps_pip = self._camera_fps.get(mc, self._frame_fps)
        rec = FFmpegPipeRecorder(ff, self._frame_w, self._frame_h, fps_pip)
        try:
            rec.start(out)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Không bắt đầu ghi được", str(e))
            self._order_sm["pip"] = OrderStateMachine()
            return
        self._recorders["pip"] = rec
        self._recording_started_at["pip"] = datetime.now()
        t0 = self._recording_started_at["pip"]
        self._recording_burnin["pip"] = RecordingBurnIn(
            order, self._config.packer_label, t0
        )
        self._station_recording_order["pip"] = order
        self._pip_last_frame.clear()
        interval = max(16, int(1000 / max(1, fps_pip)))
        self._pip_timer.start(interval)
        self._refresh_worker_recording_flags()
        self._chip.setText(f"PIP đang ghi: {order}")
        self._chip.setStyleSheet(_CHIP_REC_STYLE)
        self._sync_recording_elapsed_timer()
        if dup:
            self._feedback.play_quad()
        else:
            self._feedback.play_short()

    def _stop_recording_for_station(self, station_id: str) -> None:
        if self._config.multi_camera_mode == "pip" and station_id == "pip":
            self._pip_timer.stop()
        self._clear_recording_pace_state(station_id)
        rec = self._recorders.get(station_id)
        if rec:
            try:
                rec.stop()
            except Exception:
                pass
            self._recorders[station_id] = None
        self._maybe_stop_record_pace_timer()
        self._station_recording_order.pop(station_id, None)
        self._recording_started_at.pop(station_id, None)
        if self._config.multi_camera_mode == "stations":
            col = self._station_column(station_id)
            if col is not None:
                self._dual_panel.set_column_recording_banner(col, None)
                self._dual_panel.set_column_recording_timer(col, None)
            self._sync_stations_recording_chip()
        self._refresh_worker_recording_flags()
        self._sync_recording_elapsed_timer()

    def _stop_all_recording_for_shutdown(self) -> None:
        self._pip_timer.stop()
        self._record_pace_timer.stop()
        for sid in list(self._recorders.keys()):
            self._stop_recording_for_station(sid)
        self._station_recording_order.clear()
        self._recording_started_at.clear()
        if self._config.multi_camera_mode == "stations":
            self._dual_panel.clear_recording_banners()
            self._dual_panel.clear_recording_timers()
        self._rec_elapsed_timer.stop()
        self._rec_elapsed_resync_wall_second = True
        self._rec_elapsed_bar.clear()
        self._rec_elapsed_bar.setVisible(False)
        self._chip.setText("Chờ quét mã đơn")
        self._chip.setStyleSheet(_CHIP_IDLE_STYLE)

    def _stop_recording_after_scan(self, station_id: str, r: ScanResult) -> None:
        if self._config.multi_camera_mode == "pip" and station_id == "pip":
            self._pip_timer.stop()
        self._clear_recording_pace_state(station_id)
        rec = self._recorders.get(station_id)
        if rec:
            try:
                rec.stop()
            except Exception:
                pass
            self._recorders[station_id] = None
        self._maybe_stop_record_pace_timer()
        self._station_recording_order.pop(station_id, None)
        self._recording_started_at.pop(station_id, None)
        if self._config.multi_camera_mode == "stations":
            col = self._station_column(station_id)
            if col is not None:
                self._dual_panel.set_column_recording_banner(col, None)
                self._dual_panel.set_column_recording_timer(col, None)
        self._feedback.play_double()
        self._refresh_worker_recording_flags()
        sm = self._order_sm.get(station_id)
        if sm is None:
            return
        nr = sm.notify_stop_confirmed()
        if nr.should_start_recording and nr.new_active_order:
            if self._config.multi_camera_mode == "pip":
                self._begin_recording_pip(
                    nr.new_active_order, check_dup=nr.should_check_duplicate
                )
            else:
                self._begin_recording_station(
                    station_id,
                    nr.new_active_order,
                    check_dup=nr.should_check_duplicate,
                )
        else:
            if self._config.multi_camera_mode == "stations":
                self._sync_stations_recording_chip()
            else:
                self._chip.setText("Chờ quét mã đơn")
                self._chip.setStyleSheet(_CHIP_IDLE_STYLE)
            self._sync_recording_elapsed_timer()

    def _pause_scan_workers(self) -> None:
        self._pip_timer.stop()
        self._record_pace_timer.stop()
        self._stop_serial_workers()
        for w in list(self._workers.values()):
            w.stop_worker()
        for w in list(self._workers.values()):
            w.wait(5000)
        self._workers.clear()

    def _show_ffmpeg_missing_dialog(self) -> None:
        msg = QMessageBox(self)
        msg.setIcon(QMessageBox.Icon.Warning)
        msg.setWindowTitle("Thiếu ffmpeg")
        msg.setText("Không tìm thấy ffmpeg để nén và ghi video.")
        msg.setInformativeText(
            "Bạn có thể:\n"
            "• Cài ffmpeg và thêm vào PATH — ví dụ PowerShell: winget install ffmpeg\n"
            "• Hoặc tải bản Windows (ví dụ https://www.gyan.dev/ffmpeg/builds/ ), "
            "giải nén và bấm «Mở Cài đặt» để chỉ tới ffmpeg.exe\n"
            "• Hoặc gõ đường dẫn đầy đủ tới ffmpeg.exe trong ô «Đường dẫn ffmpeg» ở Cài đặt"
        )
        msg.addButton("Đóng", QMessageBox.ButtonRole.RejectRole)
        btn_settings = msg.addButton("Mở Cài đặt", QMessageBox.ButtonRole.ActionRole)
        btn_dl = msg.addButton("Trang tải ffmpeg", QMessageBox.ButtonRole.ActionRole)
        msg.exec()
        clicked = msg.clickedButton()
        if clicked == btn_settings:
            self._open_settings()
        elif clicked == btn_dl:
            QDesktopServices.openUrl(QUrl("https://www.gyan.dev/ffmpeg/builds/"))

    def _open_error_log_folder(self) -> None:
        p = session_log_path().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        url = QUrl.fromLocalFile(str(p.parent))
        if not QDesktopServices.openUrl(url):
            QMessageBox.information(
                self,
                "Thư mục log",
                f"Mở thủ công trong Explorer:\n{p.parent}",
            )

    def _open_settings(self) -> None:
        if any(r is not None for r in self._recorders.values()):
            QMessageBox.warning(
                self,
                "Đang ghi hình",
                "Vui lòng dừng ghi (quét lại cùng mã đơn hoặc đóng phiên) trước khi mở Cài đặt "
                "để xem trước camera.",
            )
            return
        self._pause_scan_workers()
        dlg = SettingsDialog(self._config, self)
        try:
            if dlg.exec():
                self._config = dlg.result_config()
                ensure_dual_stations(self._config)
                self._config = normalize_config(self._config)
                save_config(self._config_path, self._config)
                self._feedback.update_config(self._config)
                self._refresh_next_shutdown()
                self._rebuild_order_machines()
                self._update_packer_message()
                self._update_central_page()
        finally:
            dlg.dispose_preview()
            self._restart_scan_workers()

    def _cleanup_workers(self) -> None:
        self._pip_timer.stop()
        self._rec_elapsed_timer.stop()
        self._rec_elapsed_resync_wall_second = True
        self._stop_serial_workers()
        for w in self._workers.values():
            w.stop_worker()
        for w in self._workers.values():
            w.wait(5000)
        self._workers.clear()

    def _sync_dual_cinema_mode(self) -> None:
        st = self.windowState()
        cinema = bool(
            st & Qt.WindowState.WindowMaximized
            or st & Qt.WindowState.WindowFullScreen
        )
        if (
            self._config.multi_camera_mode == "stations"
            and self._stack.currentWidget() is self._dual_panel
        ):
            self._dual_panel.set_cinema_mode(cinema)
            self.menuBar().setVisible(not cinema)
        else:
            self.menuBar().setVisible(True)

    def showEvent(self, event: QShowEvent) -> None:  # noqa: N802
        super().showEvent(event)
        QTimer.singleShot(0, self._sync_dual_cinema_mode)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_dual_cinema_mode()
        super().changeEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        mark_session_phase("MainWindow.closeEvent — người dùng hoặc hệ thống đóng cửa sổ.")
        self._stop_all_recording_for_shutdown()
        self._cleanup_workers()
        super().closeEvent(event)
