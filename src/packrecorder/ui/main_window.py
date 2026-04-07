from __future__ import annotations

import time
from dataclasses import replace
from datetime import date, datetime, time as time_cls
from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtCore import QEvent, QPointF, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction,
    QBrush,
    QDesktopServices,
    QIcon,
    QImage,
    QPainter,
    QPen,
    QColor,
    QPixmap,
    QPolygonF,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QComboBox,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStackedWidget,
    QStatusBar,
    QToolBar,
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
    station_record_cam_id,
    station_uses_serial_scanner,
)
from packrecorder.ffmpeg_locate import resolve_ffmpeg as _resolve_ffmpeg
from packrecorder.ffmpeg_pipe_recorder import FFmpegPipeRecorder
from packrecorder.feedback_sound import FeedbackPlayer
from packrecorder.order_input import normalize_manual_order_text
from packrecorder.order_state import OrderStateMachine, ScanResult
from packrecorder.paths import build_output_path
from packrecorder.record_roi import norm_to_pixels
from packrecorder.record_resolution import (
    PRESET_LABELS_VI,
    PRESET_ORDER,
    normalize_record_resolution_preset,
    target_dimensions_for_preset,
)
from packrecorder.pip_composite import composite_pip_bgr
from packrecorder.retention import purge_old_day_folders
from packrecorder.session_log import log_session_error, mark_session_phase, session_log_path
from packrecorder.ipc.encode_writer_worker import mp_encode_writer_entry
from packrecorder.ipc.pipeline import MpCameraPipeline
from packrecorder.ipc.subprocess_recorder import SubprocessRecordingHandle
from packrecorder.scan_worker import ScanWorker
from packrecorder.serial_scan_worker import SerialScanWorker
from packrecorder.shutdown_scheduler import compute_next_shutdown_at
from packrecorder.ui.countdown_dialog import ShutdownCountdownDialog
from packrecorder.ui.dual_station_widget import DualStationWidget
from packrecorder.ui.settings_dialog import SettingsDialog
from packrecorder.video_overlay import (
    RecordingBurnIn,
    burn_in_recording_info_bgr,
    format_elapsed_overlay,
    render_recording_overlay_chip_rgba,
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
# Chỉ dùng cho máy quét COM: chặn hai lần gửi cùng mã quá sát (lần 2 = lặp kỹ thuật).
# Nhập tay + Enter: không debounce — mỗi Enter luôn gửi nội dung ô hiện tại.
_SERIAL_SAME_CODE_DEBOUNCE_S = 0.45
_DEFAULT_RECORDING_FPS = 30


def _pin_icon() -> QIcon:
    """Icon ghim nhỏ cho nút «Luôn trên cùng»."""
    s = 22
    pix = QPixmap(s, s)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(13, 71, 161), 1.2))
    p.setBrush(QBrush(QColor(100, 181, 246)))
    p.drawEllipse(5.0, 3.5, 12.0, 12.0)
    p.setBrush(QBrush(QColor(25, 118, 210)))
    tri = QPolygonF([QPointF(7.5, 15.5), QPointF(14.5, 15.5), QPointF(11.0, s - 1.0)])
    p.drawPolygon(tri)
    p.end()
    return QIcon(pix)


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
        self._did_startup_focus = False
        self.setWindowTitle("Pack Recorder")
        self._config_path = default_config_path()
        self._config = load_config(self._config_path)
        ensure_dual_stations(self._config)
        self._config = normalize_config(self._config)
        save_config(self._config_path, self._config)
        self.setWindowFlag(
            Qt.WindowType.WindowStaysOnTopHint,
            self._config.window_always_on_top,
        )
        self._next_shutdown_at: Optional[datetime] = None
        self._next_shutdown_ref: list[Optional[datetime]] = [None]
        self._refresh_next_shutdown()
        self._feedback = FeedbackPlayer(self._config)
        self._shutdown_countdown = False
        self._countdown_dialog: Optional[ShutdownCountdownDialog] = None

        self._workers: dict[int, ScanWorker] = {}
        self._mp_pipelines: dict[int, MpCameraPipeline] = {}
        self._mp_preview_last_mono: dict[int, float] = {}
        self._serial_workers: dict[str, SerialScanWorker] = {}
        self._preview_targets: dict[int, list[int]] = {}
        self._pip_wh: dict[int, tuple[int, int]] = {}
        self._camera_fps: dict[int, int] = {}
        self._pip_last_frame: dict[int, bytes] = {}
        self._frame_w, self._frame_h, self._frame_fps = (
            640,
            480,
            _DEFAULT_RECORDING_FPS,
        )
        self._serial_submit_debounce: dict[str, tuple[str, float]] = {}
        self._debug_preview_logs_left = 3  # agent log: throttle _on_worker_preview
        self._restart_in_progress = False
        self._restart_pending = False
        self._rtsp_error_shown: set[int] = set()

        self._order_sm: dict[str, OrderStateMachine] = {}
        self._recorders: dict[
            str, FFmpegPipeRecorder | SubprocessRecordingHandle | None
        ] = {}
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
        self._mp_service_timer = QTimer(self)
        self._mp_service_timer.setInterval(15)
        self._mp_service_timer.timeout.connect(self._mp_service_tick)
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
        self._dual_panel.rtsp_connect_requested.connect(self._on_rtsp_connect_requested)
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

        res_bar = QToolBar("Độ phân giải ghi", self)
        res_bar.setMovable(False)
        res_bar.addWidget(QLabel("Độ phân giải ghi: "))
        self._record_resolution_combo = QComboBox()
        self._record_resolution_combo.setMinimumWidth(300)
        for p in PRESET_ORDER:
            self._record_resolution_combo.addItem(PRESET_LABELS_VI[p], p)
        self._sync_record_resolution_combo_from_config()
        self._record_resolution_combo.currentIndexChanged.connect(
            self._on_record_resolution_combo_changed
        )
        res_bar.addWidget(self._record_resolution_combo)
        self.addToolBar(res_bar)

        pin_bar = QToolBar("Cửa sổ", self)
        pin_bar.setMovable(False)
        self._act_always_top = QAction(_pin_icon(), "Luôn trên cùng", self)
        self._act_always_top.setCheckable(True)
        self._act_always_top.setChecked(self._config.window_always_on_top)
        self._act_always_top.setToolTip(
            "Ghim cửa sổ luôn nổi trên app khác.\n"
            "• Máy quét COM: không cần ghim vẫn nhận mã.\n"
            "• Máy quét kiểu bàn phím: ghim + tiêu điểm ở ô «Mã đơn» giúp ký tự vào đúng app "
            "(triệt để hơn: chỉ dùng COM/serial hoặc đọc mã bằng camera trong app)."
        )
        self._act_always_top.toggled.connect(self._on_always_on_top_toggled)
        pin_bar.addAction(self._act_always_top)
        self.addToolBar(pin_bar)

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

    def _apply_always_on_top(self, on: bool) -> None:
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, on)
        self.show()
        self.raise_()

    def _on_always_on_top_toggled(self, checked: bool) -> None:
        self._apply_always_on_top(checked)
        if checked == self._config.window_always_on_top:
            return
        self._config = replace(self._config, window_always_on_top=checked)
        save_config(self._config_path, self._config)

    def _sync_always_on_top_from_config(self) -> None:
        on = self._config.window_always_on_top
        self._act_always_top.blockSignals(True)
        self._act_always_top.setChecked(on)
        self._act_always_top.blockSignals(False)
        self._apply_always_on_top(on)

    def _focus_for_scanner_wedge(self) -> None:
        if self._config.multi_camera_mode != "stations":
            return
        if self._stack.currentWidget() is not self._dual_panel:
            return
        self.activateWindow()
        self.raise_()
        self._dual_panel.focus_default_order_input()

    def _sync_record_resolution_combo_from_config(self) -> None:
        rr = normalize_record_resolution_preset(self._config.record_resolution)
        ix = self._record_resolution_combo.findData(rr)
        if ix < 0:
            ix = self._record_resolution_combo.findData("native")
        self._record_resolution_combo.blockSignals(True)
        self._record_resolution_combo.setCurrentIndex(max(0, ix))
        self._record_resolution_combo.blockSignals(False)

    def _on_record_resolution_combo_changed(self) -> None:
        data = self._record_resolution_combo.currentData()
        rr = normalize_record_resolution_preset(
            data if isinstance(data, str) else "native"
        )
        if rr == normalize_record_resolution_preset(self._config.record_resolution):
            return
        if any(r is not None for r in self._recorders.values()):
            self._sync_record_resolution_combo_from_config()
            QMessageBox.warning(
                self,
                "Đang ghi hình",
                "Không đổi độ phân giải khi đang ghi. Dừng ghi trước.",
            )
            return
        self._pause_scan_workers()
        self._config = replace(self._config, record_resolution=rr)
        self._config = normalize_config(self._config)
        save_config(self._config_path, self._config)
        self._restart_scan_workers()

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

    def _on_rtsp_connect_requested(self, col: int, url: str) -> None:
        if self._config.multi_camera_mode != "stations":
            return
        u = (url or "").strip()
        if not u.lower().startswith("rtsp://"):
            QMessageBox.warning(
                self,
                "URL RTSP không hợp lệ",
                "URL phải bắt đầu bằng rtsp://",
            )
            return
        # region agent log
        try:
            from packrecorder.debug_ndjson import dbg

            dbg(
                "H7",
                "main_window._on_rtsp_connect_requested",
                "user_requested_rtsp_connect",
                col=col,
                url_len=len(u),
            )
        except Exception:
            pass
        # endregion agent log
        self._on_dual_fields_changed()

    def _mp_service_tick(self) -> None:
        if not self._mp_pipelines:
            return
        for _cam, pl in list(self._mp_pipelines.items()):
            for msg in pl.pump_events():
                if not msg:
                    continue
                kind = msg[0]
                if kind == "capture_failed":
                    self._on_worker_capture_failed(int(msg[1]), str(msg[2]))
                elif kind == "ready":
                    self._on_camera_opened_slot(
                        int(msg[1]), int(msg[3]), int(msg[4]), int(msg[5])
                    )
            for cam_i, text in pl.pump_decodes():
                self._on_decoded(cam_i, text)
        self._refresh_mp_recording_and_preview()

    def _refresh_mp_recording_and_preview(self) -> None:
        """Cập nhật preview / buffer ghi từ SharedMemory (không qua Signal)."""
        preview_dt = 1.0 / 30.0
        now = time.monotonic()
        if self._config.multi_camera_mode == "stations":
            for cam_idx, cols in self._preview_targets.items():
                if not cols:
                    continue
                pl = self._mp_pipelines.get(cam_idx)
                if pl is None or not pl.is_ready:
                    continue
                last = self._mp_preview_last_mono.get(cam_idx, 0.0)
                if now - last < preview_dt:
                    continue
                bgr = pl.copy_latest_full_bgr_bytes()
                if bgr:
                    self._mp_preview_last_mono[cam_idx] = now
                    self._on_worker_preview(cam_idx, bgr)
        if self._config.multi_camera_mode == "pip":
            rec = self._recorders.get("pip")
            if rec:
                for cam in (
                    self._config.pip_main_camera_index,
                    self._config.pip_sub_camera_index,
                ):
                    pl = self._mp_pipelines.get(cam)
                    if pl is None or not pl.is_ready:
                        continue
                    bgr = pl.copy_latest_full_bgr_bytes()
                    if bgr:
                        self._pip_last_frame[cam] = bgr
        elif self._config.multi_camera_mode == "single":
            cam = self._config.camera_index
            pl = self._mp_pipelines.get(cam)
            if pl is not None and pl.is_ready and self._recorders.get("single"):
                roi = None
                bgr = pl.copy_latest_roi_bgr_bytes(roi)
                if bgr:
                    self._latest_record_bgr["single"] = bgr
        else:
            for i, st in enumerate(self._config.stations):
                sid = st.station_id
                if not self._recorders.get(sid):
                    continue
                cam = station_record_cam_id(st, i)
                pl = self._mp_pipelines.get(cam)
                if pl is None or not pl.is_ready:
                    continue
                roi = st.record_roi_norm
                bgr = pl.copy_latest_roi_bgr_bytes(roi)
                if bgr:
                    self._latest_record_bgr[sid] = bgr

    def _on_worker_preview(self, cam_idx: int, bgr: bytes) -> None:
        # region agent log
        if self._debug_preview_logs_left > 0:
            self._debug_preview_logs_left -= 1
            try:
                from packrecorder.debug_ndjson import dbg

                dbg(
                    "H4",
                    "main_window._on_worker_preview",
                    "enter",
                    cam_idx=cam_idx,
                    bgr_len=len(bgr) if bgr is not None else -1,
                )
            except Exception:
                pass
        # endregion agent log
        if self._config.multi_camera_mode != "stations":
            return
        cols = self._preview_targets.get(cam_idx)
        if not cols:
            return
        wh = self._pip_wh.get(cam_idx)
        if not wh:
            return
        w, h = wh
        for col in cols:
            self._dual_panel.set_preview_column(col, bgr, w, h)

    def _on_serial_decoded(self, station_id: str, text: str) -> None:
        if self._shutdown_countdown and self._countdown_dialog is not None:
            return
        text = normalize_manual_order_text(text)
        if not text:
            return
        # Chỉ khi không đang ghi: bỏ qua lần gửi thứ 2 cùng mã trong cửa sổ ngắn (wedge/COM nhảy đôi).
        # Khi đang ghi, mọi lần quét phải tới state machine (dừng / v.v.) — không chặn.
        now = time.monotonic()
        if not self._recorders.get(station_id):
            last = self._serial_submit_debounce.get(station_id)
            if (
                last
                and last[0] == text
                and (now - last[1]) < _SERIAL_SAME_CODE_DEBOUNCE_S
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

    def _on_worker_capture_failed(self, cam_idx: int, message: str) -> None:
        if cam_idx in self._rtsp_error_shown:
            return
        self._rtsp_error_shown.add(cam_idx)
        self._status.showMessage(message, 8000)
        QMessageBox.warning(self, "Lỗi kết nối RTSP", message)

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
        self._refresh_preview_roi_locks()

    def _refresh_preview_roi_locks(self) -> None:
        if self._config.multi_camera_mode != "stations":
            return
        for col, st in enumerate(self._config.stations[:2]):
            self._dual_panel.set_preview_roi_locked(
                col, bool(self._recorders.get(st.station_id))
            )

    def _station_row_index(self, st: StationConfig) -> int:
        for i, s in enumerate(self._config.stations[:2]):
            if s.station_id == st.station_id:
                return i
        return 0

    def _recording_dims_for_station(self, st: StationConfig) -> tuple[int, int]:
        idx = self._station_row_index(st)
        cam = station_record_cam_id(st, idx)
        full = self._pip_wh.get(cam)
        if not full:
            return (self._frame_w, self._frame_h)
        fw, fh = full
        roi = st.record_roi_norm
        if roi is None:
            return (fw, fh)
        _px, _py, pw, ph = norm_to_pixels(
            roi[0], roi[1], roi[2], roi[3], fw, fh, even=True
        )
        return (pw, ph)

    def _record_roi_for_camera(self, cam: int) -> Optional[tuple[float, float, float, float]]:
        if self._config.multi_camera_mode != "stations":
            return None
        for i, st in enumerate(self._config.stations[:2]):
            if station_record_cam_id(st, i) == cam:
                return st.record_roi_norm
        return None

    def _update_packer_message(self) -> None:
        hint = (
            "Đọc mã bằng camera: quét đơn → ghi; quét lại cùng mã không dừng; "
            "quét mã khác → dừng và ghi đơn mới. Máy COM: quét lại cùng mã → dừng."
        )
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
        mark_session_phase(
            "Hẹn giờ tắt máy: đã mở đếm ngược 60s — hủy bằng nút hoặc quét mã; "
            "hết giờ sẽ tắt Windows (không chỉ thoát app). Tắt tính năng: Tệp → Cài đặt."
        )
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
        for i, st in enumerate(self._config.stations):
            cams.add(station_record_cam_id(st, i))
            if not station_uses_serial_scanner(st):
                cams.add(st.decode_camera_index)
            if st.preview_display_index >= 0:
                cams.add(st.preview_display_index)
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
        if self._restart_in_progress:
            self._restart_pending = True
            # region agent log
            try:
                from packrecorder.debug_ndjson import dbg

                dbg(
                    "H3",
                    "main_window._restart_scan_workers",
                    "coalesced_restart",
                )
            except Exception:
                pass
            # endregion agent log
            return
        self._restart_in_progress = True
        # region agent log
        try:
            from packrecorder.debug_ndjson import dbg

            dbg(
                "H3",
                "main_window._restart_scan_workers",
                "start",
                mode=self._config.multi_camera_mode,
                required=sorted(self._required_camera_indices()),
            )
        except Exception:
            pass
        # endregion agent log
        try:
            self._pip_timer.stop()
            self._stop_serial_workers()
            for pl in list(self._mp_pipelines.values()):
                pl.stop()
            self._mp_pipelines.clear()
            self._mp_preview_last_mono.clear()
            self._mp_service_timer.stop()
            old_workers = list(self._workers.values())
            for w in old_workers:
                w.stop_worker()
            for w in old_workers:
                w.wait(5000)
            alive = [w.camera_index for w in old_workers if w.isRunning()]
            self._workers.clear()
            self._camera_fps.clear()
            self._serial_submit_debounce.clear()
            self._rtsp_error_shown.clear()
            self._pip_last_frame.clear()
            self._preview_targets.clear()
            if self._config.multi_camera_mode == "stations":
                self._dual_panel.clear_previews()
            if alive:
                # region agent log
                try:
                    from packrecorder.debug_ndjson import dbg

                    dbg(
                        "H3",
                        "main_window._restart_scan_workers",
                        "old_workers_still_alive",
                        alive=alive,
                    )
                except Exception:
                    pass
                # endregion agent log
                self._restart_pending = True
                QTimer.singleShot(300, self._restart_scan_workers)
                return

            is_sd = lambda: self._shutdown_countdown
            cap_wh = target_dimensions_for_preset(self._config.record_resolution)
            use_mp = self._config.use_multiprocessing_camera_pipeline
            for cam in sorted(self._required_camera_indices()):
                decode = self._camera_should_decode(cam)
                cap_src: int | str = cam
                fallback_usb_idx: int | None = None
                use_cap_wh = True
                if self._config.multi_camera_mode == "stations":
                    for i, st in enumerate(self._config.stations):
                        if station_record_cam_id(st, i) != cam:
                            continue
                        if (
                            st.record_camera_kind == "rtsp"
                            and (st.record_rtsp_url or "").strip()
                        ):
                            cap_src = (st.record_rtsp_url or "").strip()
                            fallback_usb_idx = i if 0 <= i <= 9 else 0
                            use_cap_wh = False
                        break
                roi = self._record_roi_for_camera(cam)
                if use_mp:
                    pl = MpCameraPipeline(
                        camera_index=cam,
                        capture_source=cap_src,
                        fallback_usb_index=fallback_usb_idx,
                        capture_target_wh=cap_wh if use_cap_wh else None,
                        use_capture_resolution=use_cap_wh,
                        decode_enabled=decode,
                        record_roi_norm=roi,
                        decode_every_n_frames=self._config.barcode_scan_interval_frames,
                        decode_scan_scale=self._config.barcode_scan_scale,
                        debounce_s=0.35,
                    )
                    pl.start()
                    self._mp_pipelines[cam] = pl
                else:
                    w = ScanWorker(
                        cam,
                        capture_source=cap_src,
                        fallback_usb_index=fallback_usb_idx,
                        decode_enabled=decode,
                        is_shutdown_countdown=is_sd,
                        preview_fps=30.0
                        if self._config.multi_camera_mode == "stations"
                        else 0.0,
                        capture_target_wh=cap_wh if use_cap_wh else None,
                        decode_every_n_frames=self._config.barcode_scan_interval_frames,
                        decode_scan_scale=self._config.barcode_scan_scale,
                        record_roi_norm=roi,
                    )
                    w.decoded.connect(self._on_decoded)
                    w.frame_ready.connect(self._on_frame)
                    w.camera_opened.connect(self._on_camera_opened_slot)
                    w.capture_failed.connect(self._on_worker_capture_failed)
                    if self._config.multi_camera_mode == "stations":
                        w.preview_ready.connect(self._on_worker_preview)
                    w.start()
                    self._workers[cam] = w
            if use_mp:
                self._mp_service_timer.start()
            else:
                self._mp_service_timer.stop()

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

            if self._config.multi_camera_mode == "stations":
                self._rebuild_preview_targets()
            # region agent log
            try:
                from packrecorder.debug_ndjson import dbg

                dbg(
                    "H3",
                    "main_window._restart_scan_workers",
                    "done",
                    workers=len(self._workers),
                    mp_pipelines=len(self._mp_pipelines),
                )
            except Exception:
                pass
            # endregion agent log
        finally:
            self._restart_in_progress = False
            if self._restart_pending:
                self._restart_pending = False
                QTimer.singleShot(0, self._restart_scan_workers)

    def _rebuild_preview_targets(self) -> None:
        """Camera index → các cột hiển thị preview (một camera có thể hiện ở nhiều cột)."""
        self._preview_targets.clear()
        if self._config.multi_camera_mode != "stations":
            return
        for col, st in enumerate(self._config.stations[:2]):
            cam = (
                station_record_cam_id(st, col)
                if st.preview_display_index < 0
                else st.preview_display_index
            )
            self._preview_targets.setdefault(cam, []).append(col)

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

    def _recording_src_short(self, st: StationConfig) -> str:
        if station_uses_serial_scanner(st):
            port = (st.scanner_serial_port or "").strip()
            return port if port else "COM"
        return f"cam{st.decode_camera_index}"

    def _record_camera_label_for_status(self, st: StationConfig, row: int) -> str:
        if st.record_camera_kind == "rtsp" and (st.record_rtsp_url or "").strip():
            return "RTSP"
        return f"cam{station_record_cam_id(st, row)}"

    def _station_recording_status_one_line(
        self, st: StationConfig, order: str, elapsed: str
    ) -> str:
        short_order = order if len(order) <= 36 else order[:33] + "…"
        row = self._station_row_index(st)
        rec_cam = self._record_camera_label_for_status(st, row)
        src = self._recording_src_short(st)
        return (
            f"● GHI | {st.packer_label} | Đơn {short_order} | {elapsed} "
            f"| quay:{rec_cam} | quét:{src}"
        )

    def _station_recording_overlay_pixmap(
        self, order: str, packer: str, started_at: datetime
    ) -> QPixmap | None:
        arr = render_recording_overlay_chip_rgba(
            order=order,
            packer=packer,
            wall_now=datetime.now(),
            started_at=started_at,
        )
        if arr is None or arr.size == 0:
            return None
        h, w = arr.shape[:2]
        qimg = QImage(
            arr.data,
            w,
            h,
            4 * w,
            QImage.Format.Format_RGBA8888,
        )
        qimg = qimg.copy()
        pix = QPixmap.fromImage(qimg)
        dpr = self.devicePixelRatioF()
        if dpr and dpr > 1.0:
            pix.setDevicePixelRatio(dpr)
        return pix

    def _update_station_recording_overlay_ui(
        self, col: int, st: StationConfig, order: str, started_at: datetime
    ) -> None:
        pix = self._station_recording_overlay_pixmap(order, st.packer_label, started_at)
        if pix is not None:
            self._dual_panel.set_column_recording_overlay_pixmap(col, pix)
        else:
            el = _format_recording_elapsed(started_at)
            self._dual_panel.set_column_recording_banner(
                col, self._station_recording_status_one_line(st, order, el)
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
                self._dual_panel.clear_recording_banners()
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
                        order = self._station_recording_order.get(sid, "")
                        self._update_station_recording_overlay_ui(
                            col, st, order, t0
                        )
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
            if isinstance(rec, SubprocessRecordingHandle):
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
        for i, st in enumerate(self._config.stations):
            if (
                self._recorders.get(st.station_id)
                and cam_idx == station_record_cam_id(st, i)
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
            for i, st in enumerate(self._config.stations):
                if self._recorders.get(st.station_id):
                    active_record_cams.add(station_record_cam_id(st, i))
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
        r = sm.on_scan(
            code,
            is_shutdown_countdown=False,
            same_scan_stops_recording=False,
            now_mono=time.monotonic(),
        )
        if r.should_start_recording and r.new_active_order:
            self._begin_recording_pip(r.new_active_order)
        if r.should_stop_recording:
            self._stop_recording_after_scan("pip", r)

    def _handle_decode_station(self, station_id: str, code: str) -> None:
        code = normalize_manual_order_text(code)
        if not code:
            return
        sm = self._order_sm.get(station_id)
        if sm is None:
            return
        st = self._station_by_id(station_id)
        same_stop = True
        if st is not None:
            same_stop = station_uses_serial_scanner(st)
        r = sm.on_scan(
            code,
            is_shutdown_countdown=False,
            same_scan_stops_recording=same_stop,
            now_mono=time.monotonic(),
        )
        if r.should_start_recording and r.new_active_order:
            self._begin_recording_station(station_id, r.new_active_order)
        if r.should_stop_recording:
            self._stop_recording_after_scan(station_id, r)

    def _begin_recording_station(self, station_id: str, order: str) -> None:
        st = self._station_by_id(station_id)
        if st is None:
            return
        root = Path(self._config.video_root)
        root.mkdir(parents=True, exist_ok=True)
        try:
            ff = _resolve_ffmpeg(self._config)
        except FileNotFoundError:
            self._show_ffmpeg_missing_dialog()
            self._order_sm[station_id] = OrderStateMachine()
            return
        w, h = self._recording_dims_for_station(st)
        fps_out = max(1, min(60, int(self._config.record_fps)))
        out = build_output_path(
            root, order, st.packer_label, datetime.now()
        )
        t0 = datetime.now()
        row = self._station_row_index(st)
        rec_cam = station_record_cam_id(st, row)
        pl = self._mp_pipelines.get(rec_cam)
        writer_params = (
            pl.attach_params_for_writer()
            if pl is not None and self._config.use_multiprocessing_camera_pipeline
            else None
        )
        use_subproc_writer = (
            writer_params is not None
            and self._config.multi_camera_mode != "pip"
        )
        if use_subproc_writer:
            assert pl is not None
            shm_name, fw, fh, n_sl, lseq, lslot, llock = writer_params
            try:
                handle = SubprocessRecordingHandle.start_encoder(
                    pl.context,
                    mp_encode_writer_entry,
                    (
                        shm_name,
                        fw,
                        fh,
                        n_sl,
                        lseq,
                        lslot,
                        llock,
                        st.record_roi_norm,
                        order,
                        st.packer_label,
                        t0.isoformat(),
                        str(ff),
                        str(out),
                        fps_out,
                        str(self._config.record_video_codec),
                        int(self._config.record_video_bitrate_kbps),
                        int(self._config.record_h264_crf),
                        w,
                        h,
                    ),
                )
            except OSError as e:
                QMessageBox.warning(self, "Không bắt đầu ghi được", str(e))
                self._order_sm[station_id] = OrderStateMachine()
                return
            self._recorders[station_id] = handle
        else:
            rec = FFmpegPipeRecorder(
                ff,
                w,
                h,
                fps_out,
                codec_preference=self._config.record_video_codec,
                bitrate_kbps=self._config.record_video_bitrate_kbps,
                h264_crf=self._config.record_h264_crf,
            )
            try:
                rec.start(out)
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(self, "Không bắt đầu ghi được", str(e))
                self._order_sm[station_id] = OrderStateMachine()
                return
            self._recorders[station_id] = rec
        self._recording_started_at[station_id] = t0
        self._recording_burnin[station_id] = RecordingBurnIn(
            order, st.packer_label, t0
        )
        self._recording_frame_wh[station_id] = (w, h)
        self._recording_emit_fps[station_id] = fps_out
        self._recording_next_emit_mono[station_id] = time.monotonic()
        self._latest_record_bgr.pop(station_id, None)
        sm = self._order_sm.get(station_id)
        if sm is not None:
            sm.mark_recording_started(time.monotonic())
        self._ensure_record_pace_timer()
        self._refresh_worker_recording_flags()
        if self._config.multi_camera_mode == "stations":
            self._station_recording_order[station_id] = order
            col = self._station_column(station_id)
            if col is not None:
                self._update_station_recording_overlay_ui(col, st, order, t0)
            self._sync_stations_recording_chip()
        else:
            self._station_recording_order[station_id] = order
            self._chip.setText(f"Đang ghi ({st.packer_label}): {order}")
            self._chip.setStyleSheet(_CHIP_REC_STYLE)
        self._sync_recording_elapsed_timer()
        self._feedback.play_short()
        self._refresh_preview_roi_locks()

    def _begin_recording_pip(self, order: str) -> None:
        root = Path(self._config.video_root)
        root.mkdir(parents=True, exist_ok=True)
        try:
            ff = _resolve_ffmpeg(self._config)
        except FileNotFoundError:
            self._show_ffmpeg_missing_dialog()
            self._order_sm["pip"] = OrderStateMachine()
            return
        out = build_output_path(
            root, order, self._config.packer_label, datetime.now()
        )
        fps_out = max(1, min(60, int(self._config.record_fps)))
        rec = FFmpegPipeRecorder(
            ff,
            self._frame_w,
            self._frame_h,
            fps_out,
            codec_preference=self._config.record_video_codec,
            bitrate_kbps=self._config.record_video_bitrate_kbps,
            h264_crf=self._config.record_h264_crf,
        )
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
        interval = max(16, int(1000 / max(1, fps_out)))
        self._pip_timer.start(interval)
        self._refresh_worker_recording_flags()
        self._chip.setText(f"PIP đang ghi: {order}")
        self._chip.setStyleSheet(_CHIP_REC_STYLE)
        self._sync_recording_elapsed_timer()
        pip_sm = self._order_sm.get("pip")
        if pip_sm is not None:
            pip_sm.mark_recording_started(time.monotonic())
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
        self._refresh_preview_roi_locks()

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
            self._refresh_preview_roi_locks()
            return
        nr = sm.notify_stop_confirmed()
        if nr.should_start_recording and nr.new_active_order:
            if self._config.multi_camera_mode == "pip":
                self._begin_recording_pip(nr.new_active_order)
            else:
                self._begin_recording_station(station_id, nr.new_active_order)
        else:
            if self._config.multi_camera_mode == "stations":
                self._sync_stations_recording_chip()
            else:
                self._chip.setText("Chờ quét mã đơn")
                self._chip.setStyleSheet(_CHIP_IDLE_STYLE)
            self._sync_recording_elapsed_timer()
        self._refresh_preview_roi_locks()

    def _pause_scan_workers(self) -> None:
        self._pip_timer.stop()
        self._record_pace_timer.stop()
        self._stop_serial_workers()
        for pl in list(self._mp_pipelines.values()):
            pl.stop()
        self._mp_pipelines.clear()
        self._mp_preview_last_mono.clear()
        self._mp_service_timer.stop()
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
                "Vui lòng dừng ghi (quét lại cùng mã đơn hoặc đóng phiên) trước khi mở Cài đặt.",
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
                self._sync_record_resolution_combo_from_config()
                self._sync_always_on_top_from_config()
        finally:
            self._restart_scan_workers()

    def _cleanup_workers(self) -> None:
        self._pip_timer.stop()
        self._rec_elapsed_timer.stop()
        self._rec_elapsed_resync_wall_second = True
        self._stop_serial_workers()
        for pl in list(self._mp_pipelines.values()):
            pl.stop()
        self._mp_pipelines.clear()
        self._mp_preview_last_mono.clear()
        self._mp_service_timer.stop()
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
        if not self._did_startup_focus:
            self._did_startup_focus = True
            QTimer.singleShot(100, self._focus_for_scanner_wedge)

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802
        if event.type() == QEvent.Type.WindowStateChange:
            self._sync_dual_cinema_mode()
        super().changeEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        mark_session_phase(
            "MainWindow.closeEvent — cửa sổ chính đóng (thường: bấm X / Alt+F4; "
            "hoặc môi trường chạy kết thúc tiến trình; không phải lỗi nếu bạn chủ động thoát)."
        )
        self._stop_all_recording_for_shutdown()
        self._cleanup_workers()
        super().closeEvent(event)
