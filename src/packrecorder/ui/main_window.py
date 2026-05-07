from __future__ import annotations

import json
import os
import sys
import time
import weakref
from dataclasses import replace
from datetime import date, datetime, time as time_cls
from pathlib import Path
from typing import Any, Optional

import numpy as np
from PySide6.QtCore import QEvent, QPointF, QTime, Qt, QTimer, QUrl
from PySide6.QtGui import (
    QAction,
    QBrush,
    QDesktopServices,
    QHideEvent,
    QIcon,
    QImage,
    QKeyEvent,
    QPainter,
    QPen,
    QColor,
    QPixmap,
    QPolygonF,
    QResizeEvent,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QStatusBar,
    QTabWidget,
    QSystemTrayIcon,
    QTimeEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from packrecorder.duplicate import is_duplicate_order
from packrecorder.branding import load_application_qicon
from packrecorder.config import (
    AppConfig,
    StationConfig,
    camera_should_decode_on_index,
    default_config_path,
    ensure_stations_layout,
    is_rtsp_stream_url,
    load_config,
    normalize_config,
    save_config,
    station_for_decode_camera,
    station_record_cam_id,
    station_uses_dedicated_barcode_scanner,
    station_uses_keyboard_wedge,
    station_uses_hid_pos_scanner,
    station_uses_serial_scanner,
)
from packrecorder.ffmpeg_locate import resolve_ffmpeg as _resolve_ffmpeg
from packrecorder.ffmpeg_pipe_recorder import FFmpegPipeRecorder
from packrecorder.feedback_sound import FeedbackPlayer
from packrecorder.order_input import normalize_manual_order_text
from packrecorder.order_state import OrderStateMachine, ScanResult
from packrecorder.heartbeat_consumer import office_heartbeat_state
from packrecorder.paths import build_output_path
from packrecorder.recording_index import RecordingIndex, open_recording_index
from packrecorder.shared_analytics_db import (
    append_shared_analytics_record,
    shared_analytics_db_path,
)
from packrecorder.status_publish import publish_status_json
from packrecorder.storage_resolver import choose_write_root
from packrecorder.sync_worker import BackupSyncWorker
from packrecorder.record_roi import norm_to_pixels
from packrecorder.record_resolution import (
    PRESET_LABELS_VI,
    PRESET_ORDER,
    normalize_record_resolution_preset,
    target_dimensions_for_preset,
)
from packrecorder.pip_composite import composite_pip_bgr
from packrecorder.retention import purge_old_day_folders
from packrecorder.session_log import (
    append_session_log,
    log_session_error,
    mark_session_phase,
    session_log_path,
)
from packrecorder.ipc.encode_writer_worker import mp_encode_writer_entry
from packrecorder.ipc.pipeline import MpCameraPipeline
from packrecorder.ipc.subprocess_recorder import SubprocessRecordingHandle
from packrecorder.scan_worker import ScanWorker
from packrecorder.hid_pos_scan_worker import HidPosScanWorker
from packrecorder.serial_scan_worker import SerialScanWorker
from packrecorder.shutdown_scheduler import compute_next_shutdown_at
from packrecorder.ui.countdown_dialog import ShutdownCountdownDialog
from packrecorder.ui.camera_error_messages import (
    mp_worker_error_dialog_buttons,
    mp_worker_error_dialog_text,
)
from packrecorder.ui.dual_station_widget import DualStationWidget
from packrecorder.ui.onboarding_banner import dual_station_banner_hint
from packrecorder.ui.mini_status_overlay import MiniStatusOverlay
from packrecorder.ui.window_title_summary import format_minimized_window_title
from packrecorder.ui.preview_tab_policy import should_paint_quay_preview
from packrecorder.ui.quay_menu_policy import should_show_top_level_search_action
from packrecorder.ui.recording_search_dialog import RecordingSearchPanel
from packrecorder.ui.dashboard_tab import DashboardTab
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
    "padding:8px 12px;border-radius:8px;background:#e5f3ff;color:#003778;"
    "font-family:'Segoe UI Variable','Segoe UI',sans-serif;font-weight:600;"
)
_CHIP_REC_STYLE = (
    "padding:8px 12px;border-radius:8px;background:#dff6dd;color:#0e700e;"
    "font-family:'Segoe UI Variable','Segoe UI',sans-serif;font-weight:600;"
)
_REC_ELAPSED_BAR_STYLE = (
    "padding:8px 14px;border-radius:8px;background-color:#fde7e9;color:#8f0804;"
    "font-size:15px;font-weight:bold;font-family:'Cascadia Mono',Consolas,monospace;"
    "border:1px solid #c42b1c;"
)
# Chỉ dùng cho máy quét COM: chặn hai lần gửi cùng mã quá sát (lần 2 = lặp kỹ thuật).
# Nhập tay + Enter: không debounce — mỗi Enter luôn gửi nội dung ô hiện tại.
_SERIAL_SAME_CODE_DEBOUNCE_S = 0.45
_DEFAULT_RECORDING_FPS = 30
# Sau giờ hẹn tắt máy: chỉ mở hộp đếm ngược nếu không có thao tác (chuột/bàn phím/quét…) trong khoảng này.
_SHUTDOWN_COUNTDOWN_IDLE_S = 20 * 60


def _win32_clear_native_topmost(hwnd: int) -> None:
    """Windows: gỡ cờ TOPMOST tại HWND — Qt đôi khi vẫn để cửa sổ nổi sau khi bỏ ghim."""
    try:
        import ctypes

        HWND_NOTOPMOST = -2
        SWP_NOMOVE = 0x0002
        SWP_NOSIZE = 0x0001
        SWP_NOACTIVATE = 0x0010
        ctypes.windll.user32.SetWindowPos(
            hwnd,
            HWND_NOTOPMOST,
            0,
            0,
            0,
            0,
            SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE,
        )
    except Exception:
        pass


def _main_window_title_bar_flags() -> Qt.WindowType:
    """Cờ tối thiểu để thanh tiêu đề còn nút đóng / thu gọn (sau hide+setWindowFlags trên Windows)."""
    return (
        Qt.WindowType.Window
        | Qt.WindowType.WindowTitleHint
        | Qt.WindowType.WindowCloseButtonHint
        | Qt.WindowType.WindowMinimizeButtonHint
        | Qt.WindowType.WindowMaximizeButtonHint
    )


def _pin_icon() -> QIcon:
    """Icon ghim nhỏ cho nút «Luôn trên cùng»."""
    s = 22
    pix = QPixmap(s, s)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setPen(QPen(QColor(196, 43, 28), 1.2))
    p.setBrush(QBrush(QColor(255, 132, 117)))
    p.drawEllipse(5.0, 3.5, 12.0, 12.0)
    p.setBrush(QBrush(QColor(196, 43, 28)))
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
    _active_ref: Optional[weakref.ReferenceType[MainWindow]] = None

    @classmethod
    def run_atexit_cleanup(cls) -> None:
        r = cls._active_ref
        if r is None:
            return
        w = r()
        if w is None:
            return
        try:
            if not w._shutdown_done:
                w._shutdown_application(reason="atexit")
        except Exception:
            pass

    def _kiosk_counter_ui(self) -> bool:
        """Màn Quầy tối giản: ẩn form thiết bị (spec 6.2 / 11)."""
        return (
            self._config.multi_camera_mode == "stations"
            and self._config.default_to_kiosk
            and self._config.onboarding_complete
        )

    def defer_first_run_setup_if_needed(self) -> None:
        if (
            self._config.multi_camera_mode == "stations"
            and self._config.first_run_setup_required
            and not self._config.onboarding_complete
        ):
            self._open_setup_wizard()

    def defer_kiosk_fullscreen_if_configured(self) -> None:
        if (
            self._config.multi_camera_mode == "stations"
            and self._config.kiosk_fullscreen_on_start
            and self._config.onboarding_complete
            and not self._config.first_run_setup_required
        ):
            self.showFullScreen()

    def __init__(self) -> None:
        super().__init__()
        MainWindow._active_ref = weakref.ref(self)
        self._did_startup_focus = False
        self.setWindowTitle("Pack Recorder")
        _icon = load_application_qicon()
        if _icon is not None:
            self.setWindowIcon(_icon)
        self._config_path = default_config_path()
        self._config = load_config(self._config_path)
        ensure_stations_layout(self._config)
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
        self._last_user_activity_mono = time.monotonic()

        self._workers: dict[int, ScanWorker] = {}
        self._mp_pipelines: dict[int, MpCameraPipeline] = {}
        self._mp_watchdog_last_restart_mono: dict[int, float] = {}
        self._mp_worker_error_dialog_last_mono: dict[int, float] = {}
        self._capture_fail_restart_mono: float = 0.0
        self._mp_preview_last_mono: dict[int, float] = {}
        self._serial_workers: dict[str, SerialScanWorker | HidPosScanWorker] = {}
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
        self._pending_station_preview: dict[int, tuple[bytes, int, int]] = {}
        self._station_preview_flush_scheduled: bool = False
        self._restart_in_progress = False
        self._restart_pending = False

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
        self._recording_write_meta: dict[str, dict[str, Any]] = {}
        self._single_record_cam_by_sid: dict[str, int] = {}
        self._recording_index: RecordingIndex | None = None
        self._index_degraded = False
        self._sync_worker: BackupSyncWorker | None = None
        self._office_search_stale = False

        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._rec_elapsed_bar = QLabel("")
        self._rec_elapsed_bar.setVisible(False)
        self._rec_elapsed_bar.setStyleSheet(_REC_ELAPSED_BAR_STYLE)
        self.statusBar().addPermanentWidget(self._rec_elapsed_bar)
        self._chip = QLabel("Chờ quét mã đơn")
        self._chip.setStyleSheet(_CHIP_IDLE_STYLE)
        self.statusBar().addPermanentWidget(self._chip)
        self._sync_indicator = QLabel("")
        self._sync_indicator.setMinimumWidth(160)
        self.statusBar().addPermanentWidget(self._sync_indicator)
        self._shutdown_footer_wrap = QWidget(self)
        shutdown_row = QHBoxLayout(self._shutdown_footer_wrap)
        shutdown_row.setContentsMargins(0, 0, 0, 0)
        shutdown_row.setSpacing(6)
        self._shutdown_enable_checkbox = QCheckBox("Tự động tắt máy sau")
        self._shutdown_time_edit = QTimeEdit(self)
        self._shutdown_time_edit.setDisplayFormat("HH:mm")
        shutdown_row.addWidget(self._shutdown_enable_checkbox)
        shutdown_row.addWidget(self._shutdown_time_edit)
        shutdown_row.addWidget(QLabel("hằng ngày"))
        self.statusBar().addPermanentWidget(self._shutdown_footer_wrap)
        self._shutdown_enable_checkbox.toggled.connect(
            self._on_shutdown_footer_toggled
        )
        self._shutdown_time_edit.timeChanged.connect(self._on_shutdown_time_changed)

        self._stack = QStackedWidget()
        self._dual_panel = DualStationWidget(kiosk_mode=self._kiosk_counter_ui())
        self._dual_panel.fields_changed.connect(self._on_dual_fields_changed)
        self._dual_panel.rtsp_connect_requested.connect(self._on_rtsp_connect_requested)
        self._dual_panel.refresh_devices_requested.connect(self._on_dual_refresh_devices)
        self._dual_panel.manual_order_submitted.connect(self._on_manual_order_submitted)
        self._mode_hint = QLabel(
            "Chế độ hiện tại không phải «Đa quầy». Vào Tệp → Cài đặt → chọn "
            "«Đa quầy — mỗi camera + tên + quét (tuỳ chọn 1)» để dùng màn hình 2 cột."
        )
        self._mode_hint.setWordWrap(True)
        self._mode_hint.setStyleSheet(
            "padding:28px 20px;color:#605e5c;font-size:10pt;"
            "font-family:'Segoe UI Variable','Segoe UI',sans-serif;"
        )
        self._stack.addWidget(self._dual_panel)
        self._stack.addWidget(self._mode_hint)

        self._header_title = QLabel("Pack Recorder")
        self._header_title.setStyleSheet(
            "font-size:15px;font-weight:600;color:#202020;"
            "font-family:'Segoe UI Variable','Segoe UI',sans-serif;"
        )

        self._header_video_root = QLineEdit(self._config.video_root)
        self._header_video_root.setPlaceholderText("Thư mục lưu video…")
        self._header_video_root.editingFinished.connect(
            self._on_header_video_root_changed
        )
        self._btn_header_browse_root = QPushButton("Chọn…")
        self._btn_header_browse_root.clicked.connect(self._browse_header_video_root)

        self._header_refresh_btn = QPushButton("Làm mới thiết bị")
        self._header_refresh_btn.setToolTip(
            "Quét lại camera và thiết bị máy quét đang cắm."
        )
        self._header_refresh_btn.clicked.connect(self._on_dual_refresh_devices)

        header = QWidget()
        header.setObjectName("counterHeader")
        header.setStyleSheet(
            "#counterHeader { background:#ffffff; border:1px solid #e5e5e5; "
            "border-radius:10px; }"
        )
        hrow = QHBoxLayout(header)
        hrow.setContentsMargins(12, 10, 12, 10)
        hrow.setSpacing(10)

        hrow.addWidget(self._header_title)
        self.setMinimumSize(920, 560)
        self.resize(1040, 640)

        self._record_resolution_combo = QComboBox()
        self._record_resolution_combo.setMinimumWidth(220)
        for p in PRESET_ORDER:
            self._record_resolution_combo.addItem(PRESET_LABELS_VI[p], p)
        self._sync_record_resolution_combo_from_config()
        self._record_resolution_combo.currentIndexChanged.connect(
            self._on_record_resolution_combo_changed
        )

        self._act_always_top = QAction(_pin_icon(), "Luôn trên cùng", self)
        self._act_always_top.setCheckable(True)
        self._act_always_top.setChecked(self._config.window_always_on_top)
        self._act_always_top.setToolTip(
            "Ghim cửa sổ luôn nổi trên app khác.\n"
            "• Máy quét COM: không cần ghim vẫn nhận mã.\n"
            "• Chế độ chạy nền dùng luồng quét chuyên dụng, không phụ thuộc focus."
        )
        self._act_always_top.toggled.connect(self._on_always_on_top_toggled)
        self._pin_btn = QToolButton()
        self._pin_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._pin_btn.setDefaultAction(self._act_always_top)
        self._pin_btn.setText("Ghim")
        self._btn_setup_wizard = QPushButton("Thiết lập máy & quầy")
        self._btn_setup_wizard.setToolTip(
            "Trình hướng dẫn cấu hình camera và máy quét cho từng quầy."
        )
        self._btn_setup_wizard.clicked.connect(self._open_setup_wizard)

        hrow.addWidget(self._pin_btn)
        hrow.addWidget(self._btn_setup_wizard)
        hrow.addSpacing(8)
        hrow.addWidget(QLabel("Lưu file:"))
        hrow.addWidget(self._header_video_root, 1)
        hrow.addWidget(self._btn_header_browse_root)
        hrow.addWidget(self._header_refresh_btn)
        hrow.addWidget(QLabel("Độ phân giải:"))
        hrow.addWidget(self._record_resolution_combo)

        self._counter_page = QWidget()
        counter_layout = QVBoxLayout(self._counter_page)
        counter_layout.setContentsMargins(0, 8, 0, 0)
        counter_layout.setSpacing(8)
        counter_layout.addWidget(header, 0)
        counter_layout.addWidget(self._stack, 1)

        self._search_panel = RecordingSearchPanel(
            self._config,
            office_search_stale=self._office_search_stale,
            retention_enabled=self._config.video_retention_keep_days > 0,
            on_retention_controls_changed=self._on_retention_controls_changed,
            parent=self,
        )
        self._dashboard_tab = DashboardTab(
            fetch_rows=self._dashboard_fetch_rows,
            fetch_packers=self._dashboard_fetch_packers,
            parent=self,
        )

        self._main_tabs = QTabWidget(self)
        self._main_tabs.addTab(self._counter_page, "Quầy")
        self._main_tabs.addTab(self._search_panel, "Quản lý")
        self._main_tabs.addTab(self._dashboard_tab, "Thống kê")
        self._counter_tab_index = self._main_tabs.indexOf(self._counter_page)
        self._paint_quay_preview = True
        self._main_tabs.currentChanged.connect(self._sync_quay_preview_paint_flag)
        self._sync_quay_preview_paint_flag()
        self._sync_footer_controls_from_config()

        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)
        root_layout.addWidget(self._main_tabs, 1)
        self.setCentralWidget(root)
        self._update_central_page()

        self._mini_overlay = MiniStatusOverlay(self)
        self._mini_overlay.hide()
        self._mini_overlay.request_restore_main.connect(self._restore_from_mini_overlay)
        self._mini_overlay_timer = QTimer(self)
        self._mini_overlay_timer.setInterval(400)
        self._mini_overlay_timer.timeout.connect(self._tick_mini_overlay)

        self._rebuild_order_machines()
        self._update_packer_message()

        m_settings = self.menuBar().addMenu("Tệp")
        act = QAction("Cài đặt", self)
        act.triggered.connect(self._open_settings)
        m_settings.addAction(act)
        act_wizard = QAction("Trình hướng dẫn thiết lập quầy…", self)
        act_wizard.triggered.connect(self._open_setup_wizard)
        m_settings.addAction(act_wizard)
        act_log = QAction("Mở thư mục nhật ký phiên…", self)
        act_log.setToolTip(
            "run_errors.log — nhật ký phiên (INFO khi khởi động là bình thường). "
            "Chỉ cần xem khi có ERROR/WARNING. Thư mục: folder chạy lệnh hoặc cạnh file .exe."
        )
        act_log.triggered.connect(self._open_error_log_folder)
        m_settings.addAction(act_log)

        act_search = QAction("Mở tab Quản lý / tìm kiếm video", self)
        act_search.triggered.connect(self._open_recording_search)
        has_management_tab = self._main_tabs.indexOf(self._search_panel) >= 0
        if should_show_top_level_search_action(
            has_management_tab=has_management_tab
        ):
            self.menuBar().addAction(act_search)

        self._purge_timer = QTimer(self)
        self._purge_timer.timeout.connect(self._run_retention)
        self._purge_timer.start(3 * 60 * 60 * 1000)
        QTimer.singleShot(0, self._run_retention)

        self._heartbeat_timer = QTimer(self)
        self._heartbeat_timer.timeout.connect(self._on_heartbeat_timer)
        self._heartbeat_timer.start(max(5_000, int(self._config.heartbeat_interval_ms)))
        self._office_hb_timer = QTimer(self)
        self._office_hb_timer.timeout.connect(self._on_office_heartbeat_poll)
        self._restart_office_heartbeat_timer()

        self._try_open_recording_index()
        self._restart_sync_worker()

        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.timeout.connect(self._check_shutdown)
        self._shutdown_timer.start(15_000)

        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

        self._shutdown_done = False
        self._tray: QSystemTrayIcon | None = None
        self._tray_health_timer = QTimer(self)
        self._tray_health_timer.timeout.connect(self._on_tray_health_beep)
        self._setup_system_tray()
        self._restart_tray_health_timer()

    def _make_tray_colored_icon(self, color: QColor) -> QIcon:
        pix = QPixmap(16, 16)
        pix.fill(color)
        return QIcon(pix)

    def _default_tray_icon_ok(self) -> QIcon:
        if not self.windowIcon().isNull():
            return self.windowIcon()
        return self._make_tray_colored_icon(QColor(46, 125, 50))

    def _set_tray_icon_ok(self) -> None:
        tray = getattr(self, "_tray", None)
        if tray is not None:
            tray.setIcon(self._default_tray_icon_ok())

    def _set_tray_icon_error(self) -> None:
        tray = getattr(self, "_tray", None)
        if tray is not None:
            tray.setIcon(self._make_tray_colored_icon(QColor(198, 40, 40)))

    def _setup_system_tray(self) -> None:
        if self._tray is not None:
            self._tray.hide()
            self._tray.deleteLater()
            self._tray = None
        if not self._config.minimize_to_tray:
            return
        if not QSystemTrayIcon.isSystemTrayAvailable():
            mark_session_phase(
                "CẢNH BÁO: Cấu hình «Thu vào khay» bật nhưng khay hệ thống không khả dụng "
                "(RDP, chính sách, v.v.) — cửa sổ sẽ luôn hiện; nút X sẽ thoát app."
            )
            return
        tray = QSystemTrayIcon(self)
        tray.setIcon(self._default_tray_icon_ok())
        tray.setToolTip("Pack Recorder")
        menu = QMenu()
        act_show = menu.addAction("Hiện cửa sổ")
        act_show.triggered.connect(self._show_from_tray)
        act_setup_tray = menu.addAction("Thiết lập quầy…")
        act_setup_tray.triggered.connect(self._open_setup_wizard)
        menu.addSeparator()
        act_quit = menu.addAction("Thoát")
        act_quit.triggered.connect(self._quit_from_tray)
        tray.setContextMenu(menu)
        tray.activated.connect(self._on_tray_activated)
        tray.show()
        self._tray = tray
        self._update_station_summary_displays()

    def _show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_from_tray()

    def _quit_from_tray(self) -> None:
        self._shutdown_application(reason="tray_quit")
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def _shutdown_application(self, *, reason: str = "unknown") -> None:
        if self._shutdown_done:
            return
        self._shutdown_done = True
        qa = QApplication.instance()
        if qa is not None:
            try:
                qa.removeEventFilter(self)
            except Exception:
                pass
        if self._sync_worker is not None:
            self._sync_worker.stop_worker()
            self._sync_worker.wait(4000)
            self._sync_worker = None
        self._close_recording_index()
        mark_session_phase(
            "MainWindow — thoát: đồng bộ dừng, đóng index, dừng ghi và worker "
            "(bấm X khi không dùng khay; hoặc Thoát từ khay; hoặc kết thúc tiến trình)."
        )
        self._stop_all_recording_for_shutdown()
        self._cleanup_workers()
        try:
            self._mini_overlay.hide()
            self._mini_overlay_timer.stop()
        except Exception:
            pass

    def _restart_tray_health_timer(self) -> None:
        self._tray_health_timer.stop()
        m = int(self._config.tray_health_beep_interval_min)
        if m <= 0 or not self._config.minimize_to_tray:
            return
        self._tray_health_timer.start(m * 60 * 1000)

    def _on_tray_health_beep(self) -> None:
        if self.isVisible():
            return
        if not self._config.minimize_to_tray:
            return
        self._feedback.play_health_ping(self._config.tray_health_beep_volume)

    def _maybe_tray_toast_order(self, order: str) -> None:
        if not self._config.tray_show_toast_on_order or self._tray is None:
            return
        if self.isVisible():
            return
        short = order if len(order) <= 40 else order[:37] + "…"
        self._tray.showMessage(
            "Pack Recorder",
            f"Đang quay đơn: {short}",
            QSystemTrayIcon.MessageIcon.Information,
            2000,
        )

    def _update_tray_icon_for_pipeline_health(self) -> None:
        if self._tray is None or not self._mp_pipelines:
            return
        req = self._required_camera_indices()
        if not req:
            return
        ok = True
        for cam in req:
            pl = self._mp_pipelines.get(cam)
            if pl is None or not pl.is_ready:
                ok = False
                break
        if ok:
            self._set_tray_icon_ok()
        else:
            self._set_tray_icon_error()

    def apply_start_in_tray(self) -> None:
        if not (self._config.start_in_tray and self._config.minimize_to_tray):
            return
        if self._config.first_run_setup_required or not self._config.onboarding_complete:
            mark_session_phase(
                "Bỏ «khởi động trong khay»: cần hiển thị wizard/thiết lập lần đầu."
            )
            return
        if self._tray is None:
            self._status.showMessage(
                "Khay hệ thống không dùng được — không thể ẩn app lúc khởi động. "
                "Tắt «Thu vào khay» trong Cài đặt nếu không cần.",
                12_000,
            )
            self.raise_()
            self.activateWindow()
            return
        if (os.environ.get("PACKRECORDER_SKIP_START_TRAY_HIDE") or "").strip() == "1":
            mark_session_phase(
                "PACKRECORDER_SKIP_START_TRAY_HIDE=1 — bỏ ẩn cửa sổ lúc khởi động (giữ cửa sổ hiện)."
            )
            self._status.showMessage(
                "Đã bỏ «ẩn lúc khởi động»: biến PACKRECORDER_SKIP_START_TRAY_HIDE=1. "
                "Hoặc tắt «Khởi động chỉ hiện icon khay» trong Cài đặt.",
                14_000,
            )
            return
        delay_ms = 2800
        mark_session_phase(
            f"«Khởi động trong khay»: cửa sổ hiện ~{delay_ms // 1000}s rồi thu vào khay "
            "(icon có thể nằm sau mũi tên ^ trên taskbar Windows)."
        )
        self._status.showMessage(
            f"Cửa sổ sẽ thu vào khay sau {delay_ms // 1000}s — xem icon góc taskbar (hoặc ^). "
            "Tắt trong Cài đặt: «Khởi động chỉ hiện icon khay».",
            delay_ms + 500,
        )
        QTimer.singleShot(delay_ms, self._finish_start_in_tray_hide)

    def _finish_start_in_tray_hide(self) -> None:
        if self._shutdown_done:
            return
        if not (self._config.start_in_tray and self._config.minimize_to_tray):
            return
        if self._tray is None:
            return
        self.hide()
        self._tray.show()
        self._tray.showMessage(
            "Pack Recorder — đang chạy nền",
            "Bấm đúp icon ở khay để mở lại.\n"
            "Không thấy? Windows: mũi tên ^ cạnh đồng hồ.\n"
            "Muốn luôn thấy cửa sổ: Tệp → Cài đặt → tắt «Khởi động chỉ hiện icon khay».",
            QSystemTrayIcon.MessageIcon.Information,
            22_000,
        )

    def eventFilter(self, watched, event) -> bool:  # noqa: ANN001
        et = event.type()
        if et in (
            QEvent.Type.MouseButtonPress,
            QEvent.Type.MouseButtonDblClick,
            QEvent.Type.Wheel,
            QEvent.Type.TouchBegin,
        ):
            self._note_user_activity()
        elif et == QEvent.Type.KeyPress and isinstance(event, QKeyEvent):
            if not event.isAutoRepeat():
                self._note_user_activity()
        return super().eventFilter(watched, event)

    def _note_user_activity(self) -> None:
        """Đánh dấu người dùng vừa tương tác (để hẹn tắt máy chờ idle)."""
        self._last_user_activity_mono = time.monotonic()

    def _focus_order_input_when_pinned(self) -> None:
        if not self._config.window_always_on_top:
            return
        if self._config.multi_camera_mode != "stations":
            return
        if self._main_tabs.currentIndex() != self._counter_tab_index:
            return
        if self._stack.currentWidget() is not self._dual_panel:
            return
        app = QApplication.instance()
        if app is not None and app.activeModalWidget() is not None:
            return

        def _focus() -> None:
            try:
                self._dual_panel.focus_default_order_input()
            except Exception:
                pass

        QTimer.singleShot(0, _focus)

    def _apply_always_on_top(self, on: bool) -> None:
        """Đổi cờ luôn trên cùng — Windows thường cần hide → đổi flags → show + có khi gỡ TOPMOST Win32."""
        app = QApplication.instance()
        was_visible = self.isVisible()
        was_fullscreen = self.isFullScreen()
        geom = self.saveGeometry()
        # Phải chụp cờ trước hide(): sau hide() một số bản Qt trả thiếu WindowCloseButtonHint → mất nút X.
        # Quan trọng: tính trên int — `QWindowFlags &= ~StaysOnTop` (kiểu QFlag) trên PySide6
        # có thể thu còn ~61441 và mất hết Window/Close (xem debug H1: effective_flags 61441).
        saved = self.windowFlags()
        saved_i = int(saved)
        base_i = int(_main_window_title_bar_flags())
        st_i = int(Qt.WindowType.WindowStaysOnTopHint)
        flags_i = saved_i | base_i
        if on:
            flags_i |= st_i
        else:
            flags_i &= ~st_i
        if was_visible:
            self.hide()
            if app is not None:
                app.processEvents()

        self.setWindowFlags(Qt.WindowType(flags_i))

        if was_visible:
            self.show()
            if was_fullscreen:
                self.showFullScreen()
            else:
                self.restoreGeometry(geom)
            self.raise_()
            self.activateWindow()
            if app is not None:
                app.processEvents()

        # Sau khi tắt ghim: một số bản Qt/Windows vẫn giữ HWND TOPMOST — ép NOTOPMOST.
        if sys.platform == "win32" and was_visible and not on:
            try:
                _win32_clear_native_topmost(int(self.winId()))
            except Exception:
                pass

        if on:
            self._focus_order_input_when_pinned()

    def _on_always_on_top_toggled(self, checked: bool) -> None:
        self._note_user_activity()
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

    def _on_header_video_root_changed(self) -> None:
        self._note_user_activity()
        new_root = self._header_video_root.text().strip()
        if new_root == (self._config.video_root or "").strip():
            return
        self._config = replace(self._config, video_root=new_root)
        self._config = normalize_config(self._config)
        save_config(self._config_path, self._config)
        self._dual_panel.sync_video_root(new_root)
        self._close_recording_index()
        self._try_open_recording_index()
        self._restart_office_heartbeat_timer()
        self._restart_sync_worker()

    def _browse_header_video_root(self) -> None:
        from PySide6.QtWidgets import QFileDialog

        d = QFileDialog.getExistingDirectory(
            self,
            "Thư mục lưu video",
            self._header_video_root.text().strip() or self._config.video_root,
        )
        if not d:
            return
        self._header_video_root.setText(d)
        self._on_header_video_root_changed()

    def _sync_header_video_root_from_config(self) -> None:
        txt = self._config.video_root or ""
        if self._header_video_root.text() == txt:
            return
        self._header_video_root.blockSignals(True)
        self._header_video_root.setText(txt)
        self._header_video_root.blockSignals(False)

    def _focus_for_scanner_wedge(self) -> None:
        if self._config.scanner_com_only:
            return
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
        self._note_user_activity()
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
            ensure_stations_layout(self._config)
            self._stack.setCurrentWidget(self._dual_panel)
            self._dual_panel.sync_from_config(
                self._config, probed_override=[], fast_serial_scan=True
            )
            QTimer.singleShot(0, self._deferred_stations_scan_and_probe)
        else:
            self._stack.setCurrentWidget(self._mode_hint)
            QTimer.singleShot(0, self._restart_scan_workers)
        self._sync_quay_preview_paint_flag()
        QTimer.singleShot(0, self._refresh_onboarding_banners)

    def _refresh_onboarding_banners(self) -> None:
        if self._config.multi_camera_mode != "stations":
            return
        for col in range(min(2, len(self._config.stations))):
            st = self._config.stations[col]
            if self._recorders.get(st.station_id) is not None:
                continue
            hint = dual_station_banner_hint(self._config, col=col)
            if hint:
                self._dual_panel.set_column_recording_banner(col, hint)
            else:
                self._dual_panel.set_column_recording_banner(col, None)

    def _sync_quay_preview_paint_flag(self) -> None:
        self._paint_quay_preview = should_paint_quay_preview(
            multi_camera_mode=self._config.multi_camera_mode,
            main_tab_index=self._main_tabs.currentIndex(),
            counter_tab_index=self._counter_tab_index,
        )
        self._sync_footer_tab_visibility()

    def _sync_footer_tab_visibility(self) -> None:
        if not hasattr(self, "_main_tabs"):
            return
        is_counter_tab = self._main_tabs.currentIndex() == self._counter_tab_index
        self._shutdown_footer_wrap.setVisible(is_counter_tab)

    def _sync_footer_controls_from_config(self) -> None:
        enabled = bool(self._config.shutdown_enabled)
        self._shutdown_enable_checkbox.blockSignals(True)
        self._shutdown_enable_checkbox.setChecked(enabled)
        self._shutdown_enable_checkbox.blockSignals(False)
        t = QTime.fromString((self._config.shutdown_time_hhmm or "").strip(), "HH:mm")
        if not t.isValid():
            t = QTime(18, 0)
        self._shutdown_time_edit.blockSignals(True)
        self._shutdown_time_edit.setTime(t)
        self._shutdown_time_edit.blockSignals(False)
        self._shutdown_time_edit.setEnabled(enabled)

    def _on_retention_controls_changed(self, enabled: bool, days: int) -> None:
        self._note_user_activity()
        keep_days = int(days) if enabled else 0
        keep_days = max(0, min(3650, keep_days))
        if keep_days == int(self._config.video_retention_keep_days):
            return
        self._config = replace(self._config, video_retention_keep_days=keep_days)
        self._config = normalize_config(self._config)
        save_config(self._config_path, self._config)
        self._run_retention()

    def _on_shutdown_footer_toggled(self, enabled: bool) -> None:
        self._note_user_activity()
        self._shutdown_time_edit.setEnabled(enabled)
        hhmm = self._shutdown_time_edit.time().toString("HH:mm")
        if (
            bool(self._config.shutdown_enabled) == bool(enabled)
            and (self._config.shutdown_time_hhmm or "").strip() == hhmm
        ):
            self._refresh_next_shutdown()
            return
        self._config = replace(
            self._config,
            shutdown_enabled=bool(enabled),
            shutdown_time_hhmm=hhmm,
        )
        self._config = normalize_config(self._config)
        save_config(self._config_path, self._config)
        self._refresh_next_shutdown()

    def _on_shutdown_time_changed(self, _time: QTime) -> None:
        self._note_user_activity()
        hhmm = self._shutdown_time_edit.time().toString("HH:mm")
        if (self._config.shutdown_time_hhmm or "").strip() == hhmm:
            self._refresh_next_shutdown()
            return
        self._config = replace(self._config, shutdown_time_hhmm=hhmm)
        self._config = normalize_config(self._config)
        save_config(self._config_path, self._config)
        self._refresh_next_shutdown()

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
        self._note_user_activity()
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
            QTimer.singleShot(0, self._refresh_onboarding_banners)

    def _on_refresh_camera_probe_finished(self, found: list) -> None:
        if self._config.multi_camera_mode == "stations":
            self._dual_panel.apply_camera_probe_result(found)

    def _on_dual_fields_changed(self) -> None:
        self._note_user_activity()
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
        before_full = MainWindow._stations_full_persist_signature(self._config)
        before_worker = MainWindow._stations_worker_restart_signature(self._config)
        self._dual_panel.apply_to_config(self._config)
        self._config = normalize_config(self._config)
        after_full = MainWindow._stations_full_persist_signature(self._config)
        after_worker = MainWindow._stations_worker_restart_signature(self._config)
        if before_full == after_full:
            return
        save_config(self._config_path, self._config)
        if before_worker != after_worker:
            self._rebuild_order_machines()
            self._update_packer_message()
            self._restart_scan_workers()
        else:
            self._rebuild_preview_targets()
            self._refresh_preview_roi_locks()
        QTimer.singleShot(0, self._refresh_onboarding_banners)

    @staticmethod
    def _station_row_worker_tuple(s: StationConfig) -> tuple[object, ...]:
        """Fields that affect camera workers / pipelines / serial."""
        extras = tuple(int(x) for x in (s.extra_preview_usb_indices or []))
        return (
            s.station_id,
            s.packer_label,
            s.record_camera_kind,
            s.record_rtsp_url,
            int(s.record_camera_index),
            int(s.decode_camera_index),
            s.scanner_serial_port,
            int(s.scanner_serial_baud),
            s.scanner_usb_vid,
            s.scanner_usb_pid,
            getattr(s, "scanner_input_kind", "com"),
            int(s.preview_display_index),
            extras,
            tuple(s.record_roi_norm) if s.record_roi_norm is not None else None,
        )

    @staticmethod
    def _station_row_full_tuple(s: StationConfig) -> tuple[object, ...]:
        """Persisted station row including 1-quầy preview UI (focus/grid)."""
        return MainWindow._station_row_worker_tuple(s) + (
            s.single_station_view_mode,
            s.focused_preview_usb_index,
        )

    @staticmethod
    def _stations_worker_restart_signature(cfg: AppConfig) -> tuple[object, ...]:
        """Signature for changes that require restarting capture/decode workers."""
        stations_sig = tuple(
            MainWindow._station_row_worker_tuple(s) for s in cfg.stations[:2]
        )
        return (
            cfg.video_root,
            bool(cfg.scanner_com_only),
            stations_sig,
            cfg.multi_camera_mode,
        )

    @staticmethod
    def _stations_full_persist_signature(cfg: AppConfig) -> tuple[object, ...]:
        """Full signature — any change should be written to disk."""
        stations_sig = tuple(
            MainWindow._station_row_full_tuple(s) for s in cfg.stations[:2]
        )
        return (
            cfg.video_root,
            bool(cfg.scanner_com_only),
            stations_sig,
            cfg.multi_camera_mode,
        )

    def _on_rtsp_connect_requested(self, col: int, url: str) -> None:
        self._note_user_activity()
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
        self._on_dual_fields_changed()

    def _mp_service_tick(self) -> None:
        if not self._mp_pipelines:
            return
        try:
            for _cam, pl in list(self._mp_pipelines.items()):
                for msg in pl.pump_events():
                    if not msg:
                        continue
                    kind = msg[0]
                    if kind == "capture_failed":
                        if len(msg) >= 3:
                            self._on_worker_capture_failed(
                                int(msg[1]), str(msg[2])
                            )
                    elif kind == "worker_error":
                        if len(msg) >= 3:
                            self._on_mp_worker_error(int(msg[1]), str(msg[2]))
                    elif kind == "ready":
                        if len(msg) >= 6:
                            self._on_camera_opened_slot(
                                int(msg[1]),
                                int(msg[3]),
                                int(msg[4]),
                                int(msg[5]),
                            )
                for cam_i, text in pl.pump_decodes():
                    self._on_decoded(cam_i, text)
            stale_s = float(self._config.ipc_worker_stale_seconds)
            if stale_s > 0 and self._config.use_multiprocessing_camera_pipeline:
                noww = time.time()
                for cam, pl in list(self._mp_pipelines.items()):
                    if not pl.is_ready:
                        continue
                    if not pl.is_heartbeat_stale(noww, stale_s):
                        continue
                    last_mono = self._mp_watchdog_last_restart_mono.get(cam, 0.0)
                    if time.monotonic() - last_mono < 30.0:
                        continue
                    self._mp_watchdog_last_restart_mono[cam] = time.monotonic()
                    log_session_error(
                        f"Watchdog: camera {cam} heartbeat stale — restart pipeline."
                    )
                    try:
                        self._status.showMessage(
                            f"Camera {cam}: nhịp worker quá cũ — đang khởi động lại…",
                            15000,
                        )
                    except Exception:
                        pass
                    pl.stop()
                    QTimer.singleShot(0, self._restart_scan_workers)
                    break
            self._refresh_mp_recording_and_preview()
            self._update_tray_icon_for_pipeline_health()
        except Exception:
            import sys

            log_session_error(
                "Lỗi trong _mp_service_tick (camera MP) — app không thoát.",
                exc_info=sys.exc_info(),
            )

    def _refresh_mp_recording_and_preview(self) -> None:
        """Cập nhật preview / buffer ghi từ SharedMemory (không qua Signal)."""
        preview_dt = 1.0 / 30.0
        if not self.isVisible() and self._config.minimize_to_tray:
            preview_dt = 2.0
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
                    last = self._mp_preview_last_mono.get(cam, 0.0)
                    if now - last < preview_dt:
                        continue
                    bgr = pl.copy_latest_full_bgr_bytes()
                    if bgr:
                        self._mp_preview_last_mono[cam] = now
                        self._pip_last_frame[cam] = bgr
        elif self._config.multi_camera_mode == "single":
            if self._is_single_recording_active():
                for sid, cam in list(self._single_record_cam_by_sid.items()):
                    if not self._recorders.get(sid):
                        continue
                    pl = self._mp_pipelines.get(cam)
                    if pl is None or not pl.is_ready:
                        continue
                    bgr = pl.copy_latest_roi_bgr_bytes(None)
                    if bgr:
                        self._latest_record_bgr[sid] = bgr
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
        if self._config.multi_camera_mode != "stations":
            return
        cols = self._preview_targets.get(cam_idx)
        if not cols:
            return
        wh = self._pip_wh.get(cam_idx)
        if not wh:
            return
        w, h = wh
        # Defer ra tick kế tiếp của event loop — tránh chồng tick MP + paint (log #39: crash sau H6, trước paint)
        self._pending_station_preview[cam_idx] = (bytes(bgr), int(w), int(h))
        if not self._station_preview_flush_scheduled:
            self._station_preview_flush_scheduled = True
            QTimer.singleShot(0, self._flush_pending_station_previews)

    def _flush_pending_station_previews(self) -> None:
        self._station_preview_flush_scheduled = False
        pending = self._pending_station_preview
        self._pending_station_preview = {}
        if not self._paint_quay_preview:
            return
        if self._config.multi_camera_mode != "stations":
            return
        for cam_idx, (bgr, fw, fh) in pending.items():
            cols = self._preview_targets.get(cam_idx)
            if not cols:
                continue
            wh = self._pip_wh.get(cam_idx)
            if wh is None or int(wh[0]) != fw or int(wh[1]) != fh:
                continue
            w, h = int(wh[0]), int(wh[1])
            for col in cols:
                self._dual_panel.set_preview_column(col, cam_idx, bgr, w, h)

    def _on_serial_decoded(self, station_id: str, text: str) -> None:
        try:
            self._note_user_activity()
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
                src = (
                    "HID POS"
                    if station_uses_hid_pos_scanner(st)
                    else "USB–COM"
                    if station_uses_serial_scanner(st)
                    else "Máy quét"
                )
                self._status.showMessage(
                    f"[{st.packer_label}] {src}: {short}",
                    5000,
                )
            col = self._station_column(station_id)
            if col is not None:
                self._dual_panel.set_manual_order_text(col, text)
            self._handle_decode_station(station_id, text)
            if self._search_panel.query_input_has_focus():
                self._search_panel.append_query_text(text)
            if col is not None:
                self._dual_panel.clear_manual_order_column(col)
        except Exception:
            import sys

            log_session_error(
                "Lỗi trong _on_serial_decoded (COM / UI / decode).",
                exc_info=sys.exc_info(),
            )

    def _on_mp_worker_error(self, cam_idx: int, tb_text: str) -> None:
        """Lỗi không bắt được trong worker MP (capture/scanner) — log đầy đủ, status 30s."""
        try:
            append_session_log(
                "ERROR",
                f"MP worker camera {cam_idx}:\n{tb_text[:8000]}",
            )
            self._status.showMessage(
                f"Camera {cam_idx} không mở được — kiểm tra USB hoặc app khác đang dùng camera. "
                f"Tệp → «Thiết lập máy & quầy» nếu cần đổi thiết bị. (Chi tiết trong log phiên.)",
                30000,
            )
            self._set_tray_icon_error()
            now = time.monotonic()
            last = self._mp_worker_error_dialog_last_mono.get(cam_idx, 0.0)
            if now - last < 45.0:
                return
            self._mp_worker_error_dialog_last_mono[cam_idx] = now
            retry_lbl, setup_lbl, close_lbl = mp_worker_error_dialog_buttons()
            box = QMessageBox(self)
            box.setWindowTitle("Camera không mở được")
            box.setText(mp_worker_error_dialog_text(cam_idx))
            retry_btn = box.addButton(retry_lbl, QMessageBox.ButtonRole.AcceptRole)
            setup_btn = box.addButton(setup_lbl, QMessageBox.ButtonRole.ActionRole)
            box.addButton(close_lbl, QMessageBox.ButtonRole.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked == retry_btn:
                QTimer.singleShot(0, self._restart_scan_workers)
            elif clicked == setup_btn:
                QTimer.singleShot(0, self._open_setup_wizard)
        except Exception:
            import sys

            log_session_error(
                "Lỗi trong _on_mp_worker_error.",
                exc_info=sys.exc_info(),
            )

    def _on_worker_capture_failed(self, _cam_idx: int, message: str) -> None:
        """MP / ScanWorker: mất tín hiệu camera; MP có thể khởi động lại pipeline sau hotplug (debounce).

        Chủ yếu báo thanh trạng thái + icon khay — không popup hàng loạt.
        """
        try:
            self._status.showMessage(message, 12000)
            self._set_tray_icon_error()
            # USB hotplug: pipeline đôi khi báo capture_failed — thử restart một lần sau vài giây (tránh vòng lặp).
            if self._config.use_multiprocessing_camera_pipeline:
                now = time.monotonic()
                if now - self._capture_fail_restart_mono >= 12.0:
                    self._capture_fail_restart_mono = now
                    QTimer.singleShot(
                        2500,
                        self._restart_scan_workers,
                    )
        except Exception:
            import sys

            log_session_error(
                "Lỗi trong _on_worker_capture_failed — app không thoát.",
                exc_info=sys.exc_info(),
            )

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

    def _new_order_state_machine(self) -> OrderStateMachine:
        return OrderStateMachine(
            transition_cooldown_s=self._config.order_transition_cooldown_s,
        )

    def _rebuild_order_machines(self) -> None:
        self._order_sm = {
            s.station_id: self._new_order_state_machine()
            for s in self._effective_stations()
        }
        self._recorders = {s.station_id: None for s in self._effective_stations()}
        self._single_record_cam_by_sid.clear()
        self._refresh_preview_roi_locks()

    def _single_record_sid(self, cam: int) -> str:
        return f"single#cam{int(cam)}"

    def _single_recording_sids(self) -> list[str]:
        return [
            sid
            for sid in self._single_record_cam_by_sid
            if sid in self._recorders
        ]

    def _is_single_recording_active(self) -> bool:
        return any(
            self._recorders.get(sid) is not None for sid in self._single_recording_sids()
        )

    def _refresh_preview_roi_locks(self) -> None:
        if self._config.multi_camera_mode != "stations":
            return
        for col, st in enumerate(self._config.stations[:2]):
            rec_lock = bool(self._recorders.get(st.station_id))
            single = self._dual_panel.single_station_roi_should_lock()
            lock = rec_lock or (single if col == 0 else False)
            self._dual_panel.set_preview_roi_locked(col, lock)

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
        idle_s = time.monotonic() - self._last_user_activity_mono
        if idle_s < _SHUTDOWN_COUNTDOWN_IDLE_S:
            return
        self._begin_shutdown_sequence()

    def _begin_shutdown_sequence(self) -> None:
        mark_session_phase(
            "Hẹn giờ tắt máy: đã mở đếm ngược 60s (chỉ sau khi qua giờ hẹn và không có thao tác "
            f"{_SHUTDOWN_COUNTDOWN_IDLE_S // 60} phút) — hủy bằng nút hoặc quét mã; "
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
        keep = max(0, int(self._config.video_retention_keep_days))
        if keep <= 0:
            return
        root = Path(self._config.video_root)
        if root.is_dir():
            purge_old_day_folders(root, keep, date.today())
        br = (self._config.video_backup_root or "").strip()
        if br:
            bp = Path(br)
            if bp.is_dir():
                purge_old_day_folders(bp, keep, date.today())

    def _try_open_recording_index(self) -> None:
        self._close_recording_index()
        try:
            self._recording_index, self._index_degraded = open_recording_index(self._config)
        except OSError:
            self._recording_index = None
            self._index_degraded = True

    def _close_recording_index(self) -> None:
        if self._recording_index is not None:
            self._recording_index.close()
            self._recording_index = None

    def _restart_sync_worker(self) -> None:
        if self._sync_worker is not None:
            self._sync_worker.stop_worker()
            self._sync_worker.wait(4000)
            self._sync_worker = None
        if not (self._config.video_backup_root or "").strip():
            return
        if self._recording_index is None:
            return
        db_path = self._recording_index.db_path
        self._sync_worker = BackupSyncWorker(
            db_path, self._config.sync_worker_interval_ms, self
        )
        self._sync_worker.sync_failed.connect(
            lambda m: self._status.showMessage(f"Đưa video lên ổ chính: {m}", 10_000)
        )
        self._sync_worker.start()

    def _restart_office_heartbeat_timer(self) -> None:
        self._office_hb_timer.stop()
        if (self._config.remote_status_json_path or "").strip():
            self._office_hb_timer.start(
                max(5_000, int(self._config.office_heartbeat_poll_ms))
            )
            QTimer.singleShot(0, self._on_office_heartbeat_poll)

    def _publish_status_json_core(self) -> tuple[bool, bool] | None:
        # Máy "office/receiver" (đã cấu hình đọc heartbeat từ máy khác)
        # chỉ nhận tín hiệu, không tự phát heartbeat nội bộ.
        if (self._config.remote_status_json_path or "").strip():
            return None
        vr = (self._config.video_root or "").strip()
        br = (self._config.video_backup_root or "").strip()
        if not vr and not br:
            return None
        return publish_status_json(
            self._config, index_degraded=self._index_degraded
        )

    def _apply_publisher_sync_label(self, po: bool, bo: bool) -> None:
        br = (self._config.video_backup_root or "").strip()
        if br:
            if bo:
                self._sync_indicator.setText("Đồng bộ: ổn (cả ổ dự phòng)")
                self._sync_indicator.setStyleSheet("color:#107c10;font-weight:bold;")
            else:
                self._sync_indicator.setText("Cảnh báo: không ghi được file trạng thái (ổ dự phòng)")
                self._sync_indicator.setStyleSheet("color:#c42b1c;font-weight:bold;")
        else:
            if po:
                self._sync_indicator.setText("Đồng bộ: ổn")
                self._sync_indicator.setStyleSheet("color:#107c10;font-weight:bold;")
            else:
                self._sync_indicator.setText("Cảnh báo: không ghi được file trạng thái")
                self._sync_indicator.setStyleSheet("color:#c42b1c;font-weight:bold;")

    def _on_heartbeat_timer(self) -> None:
        r = self._publish_status_json_core()
        if r is None:
            return
        po, bo = r
        if (self._config.remote_status_json_path or "").strip():
            return
        self._apply_publisher_sync_label(po, bo)

    def _on_office_heartbeat_poll(self) -> None:
        path = (self._config.remote_status_json_path or "").strip()
        if not path:
            return
        p = Path(path)
        age = 1e9
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                lh = str(data.get("last_heartbeat") or "")
                ts = datetime.fromisoformat(lh)
                age = max(0.0, (datetime.now() - ts.replace(tzinfo=None)).total_seconds())
            except (ValueError, TypeError, OSError, json.JSONDecodeError):
                age = 1e9
        light, msg, stale = office_heartbeat_state(
            age,
            fresh_s=int(self._config.heartbeat_fresh_seconds),
            stale_s=int(self._config.heartbeat_stale_seconds),
        )
        self._office_search_stale = stale
        colors = {"green": "#107c10", "yellow": "#ca5010", "red": "#c42b1c"}
        short = msg if len(msg) <= 100 else msg[:97] + "…"
        self._sync_indicator.setText(short)
        self._sync_indicator.setStyleSheet(
            f"color: {colors.get(light, '#202020')};font-weight:bold;"
        )

    def _heartbeat_after_recording(self) -> None:
        r = self._publish_status_json_core()
        if r is None:
            return
        po, bo = r
        if (self._config.remote_status_json_path or "").strip():
            return
        self._apply_publisher_sync_label(po, bo)

    def _finalize_saved_recording(self, station_id: str) -> None:
        meta = self._recording_write_meta.pop(station_id, None)
        if meta is None:
            self._heartbeat_after_recording()
            return
        if self._recording_index is None:
            self._try_open_recording_index()
        if self._recording_index is None:
            self._heartbeat_after_recording()
            return
        primary_root = str(Path(self._config.video_root).resolve())
        backup_opt = (self._config.video_backup_root or "").strip()
        st_s = "synced" if meta["tag"] == "primary" else "pending_upload"
        station_name = station_id
        station = self._station_by_id(station_id)
        if station is not None:
            station_name = station.packer_label
        elif station_id.startswith("single#cam"):
            try:
                cam = int(station_id.split("#cam", 1)[1])
                station_name = f"{self._config.packer_label}-cam{cam}"
            except (TypeError, ValueError):
                station_name = self._config.packer_label
        duration_s = 0.0
        try:
            started_dt = datetime.fromisoformat(str(meta["started"]))
            duration_s = max(0.0, (datetime.now() - started_dt).total_seconds())
        except (TypeError, ValueError):
            duration_s = 0.0
        try:
            record_uid = (
                f"{self._config.machine_id}|{station_name}|{meta['order']}|{meta['started']}|{meta['rel_key']}"
            )
            self._recording_index.insert(
                order_id=meta["order"],
                packer=meta["packer"],
                software_id=self._config.software_id,
                machine_id=self._config.machine_id,
                station_name=station_name,
                record_uid=record_uid,
                rel_key=meta["rel_key"],
                storage_status=st_s,
                primary_root=primary_root,
                backup_root=backup_opt or None,
                resolved_path=str(Path(meta["out"]).resolve()),
                created_at=meta["started"],
                duration_seconds=duration_s,
            )
        except OSError as e:
            log_session_error(f"recording_index.insert failed: {e}")
        try:
            append_shared_analytics_record(
                self._config,
                order_id=meta["order"],
                packer=meta["packer"],
                station_name=station_name,
                rel_key=meta["rel_key"],
                storage_status=st_s,
                primary_root=primary_root,
                backup_root=backup_opt or None,
                resolved_path=str(Path(meta["out"]).resolve()),
                created_at=meta["started"],
                duration_seconds=duration_s,
            )
        except OSError as e:
            log_session_error(f"shared analytics insert failed: {e}")
        self._heartbeat_after_recording()

    def _open_recording_search(self) -> None:
        self._note_user_activity()
        idx = self._main_tabs.indexOf(self._search_panel)
        if idx >= 0:
            self._main_tabs.setCurrentIndex(idx)

    def _dashboard_fetch_rows(
        self,
        from_iso: str,
        to_iso: str,
        packer: str | None,
    ) -> list[dict[str, Any]]:
        shared_db = shared_analytics_db_path(self._config)
        db_path = (
            shared_db
            if shared_db is not None and shared_db.is_file()
            else (
                self._recording_index.db_path
                if self._recording_index is not None
                else None
            )
        )
        if db_path is None or not db_path.is_file():
            return []
        idx = RecordingIndex(db_path)
        idx.connect(uri_readonly=True)
        try:
            return idx.search_dashboard(
                date_from=from_iso,
                date_to=to_iso,
                software_id=self._config.software_id,
                packer=packer,
                limit=5000,
            )
        finally:
            idx.close()

    def _dashboard_fetch_packers(self, from_iso: str, to_iso: str) -> list[str]:
        shared_db = shared_analytics_db_path(self._config)
        db_path = (
            shared_db
            if shared_db is not None and shared_db.is_file()
            else (
                self._recording_index.db_path
                if self._recording_index is not None
                else None
            )
        )
        if db_path is None or not db_path.is_file():
            return []
        idx = RecordingIndex(db_path)
        idx.connect(uri_readonly=True)
        try:
            return idx.distinct_packers(
                date_from=from_iso,
                date_to=to_iso,
                software_id=self._config.software_id,
            )
        finally:
            idx.close()

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
            if not station_uses_dedicated_barcode_scanner(st):
                cams.add(st.decode_camera_index)
            if st.preview_display_index >= 0:
                cams.add(st.preview_display_index)
            for usb_idx in st.extra_preview_usb_indices or []:
                if 0 <= int(usb_idx) <= 9:
                    cams.add(int(usb_idx))
        return cams

    def _camera_should_decode(self, cam: int) -> bool:
        if self._config.multi_camera_mode == "single":
            return True
        if self._config.multi_camera_mode == "pip":
            return cam == self._config.pip_decode_camera_index
        if (
            self._config.multi_camera_mode == "stations"
            and self._dual_panel.station_column_count() == 1
            and self._config.stations
        ):
            st0 = self._config.stations[0]
            decode_set: set[int] = {station_record_cam_id(st0, 0)}
            for usb_idx in st0.extra_preview_usb_indices or []:
                ui = int(usb_idx)
                if 0 <= ui <= 9:
                    decode_set.add(ui)
            return int(cam) in decode_set
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
            return
        self._restart_in_progress = True
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
            self._pip_last_frame.clear()
            self._preview_targets.clear()
            if self._config.multi_camera_mode == "stations":
                self._dual_panel.clear_previews()
            if alive:
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
                        if st.record_camera_kind == "rtsp" and is_rtsp_stream_url(
                            st.record_rtsp_url
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
                    if station_uses_hid_pos_scanner(st):
                        hw = HidPosScanWorker(
                            st.station_id,
                            st.scanner_usb_vid,
                            st.scanner_usb_pid,
                        )
                        hw.line_decoded.connect(
                            self._on_serial_decoded,
                            Qt.ConnectionType.QueuedConnection,
                        )
                        hw.failed.connect(
                            self._on_serial_failed,
                            Qt.ConnectionType.QueuedConnection,
                        )
                        hw.start()
                        self._serial_workers[st.station_id] = hw
                    elif station_uses_serial_scanner(st):
                        port = st.scanner_serial_port.strip()
                        if not port:
                            continue
                        sw = SerialScanWorker(
                            st.station_id,
                            port,
                            baudrate=st.scanner_serial_baud,
                        )
                        sw.line_decoded.connect(
                            self._on_serial_decoded,
                            Qt.ConnectionType.QueuedConnection,
                        )
                        sw.failed.connect(
                            self._on_serial_failed,
                            Qt.ConnectionType.QueuedConnection,
                        )
                        sw.start()
                        self._serial_workers[st.station_id] = sw

            if self._config.multi_camera_mode == "stations":
                self._rebuild_preview_targets()
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
        ncols = min(self._dual_panel.station_column_count(), len(self._config.stations))
        for col in range(ncols):
            st = self._config.stations[col]
            rec = station_record_cam_id(st, col)
            preview_cams: set[int] = {rec}
            for usb_idx in st.extra_preview_usb_indices or []:
                ui = int(usb_idx)
                if 0 <= ui <= 9:
                    preview_cams.add(ui)
            if st.preview_display_index >= 0:
                preview_cams.add(int(st.preview_display_index))
            for cam in preview_cams:
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

    def _show_station_order_pending(self, station_id: str, order: str) -> None:
        col = self._station_column(station_id)
        if col is not None:
            self._dual_panel.set_column_order_pending(col, order)

    def _clear_station_order_pending(self, station_id: str) -> None:
        col = self._station_column(station_id)
        if col is not None:
            self._dual_panel.set_column_order_pending(col, None)

    def _recording_src_short(self, st: StationConfig) -> str:
        if station_uses_hid_pos_scanner(st):
            v = (st.scanner_usb_vid or "").strip().upper()
            p = (st.scanner_usb_pid or "").strip().upper()
            return f"HID {v}:{p}" if v and p else "HID"
        if station_uses_serial_scanner(st):
            port = (st.scanner_serial_port or "").strip()
            return port if port else "COM"
        return f"cam{st.decode_camera_index}"

    def _record_camera_label_for_status(self, st: StationConfig, row: int) -> str:
        if st.record_camera_kind == "rtsp" and is_rtsp_stream_url(st.record_rtsp_url):
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

    def _mini_overlay_line_pair(self) -> tuple[str, str]:
        texts, _kinds = self._mini_overlay_lines_styled()
        return texts

    def _mini_overlay_line_kind_for_column(self, col: int) -> str:
        if self._config.multi_camera_mode != "stations":
            return "idle"
        if col >= len(self._config.stations):
            return "idle"
        st = self._config.stations[col]
        rec = self._recorders.get(st.station_id)
        if rec is not None:
            return "recording"
        rid = station_record_cam_id(st, col)
        pl = self._mp_pipelines.get(rid)
        if pl is not None and not pl.is_ready:
            return "error"
        return "idle"

    def _mini_overlay_lines_styled(
        self,
    ) -> tuple[tuple[str, str], tuple[str, str]]:
        if self._config.multi_camera_mode != "stations":
            return (("Pack Recorder", "—"), ("idle", "idle"))
        lines: list[str] = []
        kinds: list[str] = []
        for col, st in enumerate(self._config.stations[:2]):
            oid = self._station_recording_order.get(st.station_id, "")
            rec = self._recorders.get(st.station_id)
            started_at = self._recording_started_at.get(st.station_id)
            status = "Đang ghi" if rec is not None else "Chờ quét"
            short = oid if len(oid) <= 24 else oid[:21] + "…"
            show_label = bool(getattr(st, "mini_overlay_show_label", True))
            show_state = bool(getattr(st, "mini_overlay_show_state", True))
            show_order = bool(getattr(st, "mini_overlay_show_order", True))
            show_current_time = bool(
                getattr(st, "mini_overlay_show_current_time", True)
            )
            show_packing_duration = bool(
                getattr(st, "mini_overlay_show_packing_duration", True)
            )
            parts: list[str] = []
            if show_label:
                parts.append(st.packer_label)
            if show_state:
                parts.append(status)
            if show_order and rec is not None and short:
                parts.append(short)
            if show_current_time:
                parts.append(datetime.now().strftime("%H:%M:%S"))
            if show_packing_duration:
                if rec is not None and started_at is not None:
                    parts.append(_format_recording_elapsed(started_at))
                else:
                    parts.append("00:00")
            line = " | ".join(parts).strip()
            if not line:
                line = st.packer_label
            lines.append(line)
            kinds.append(self._mini_overlay_line_kind_for_column(col))
        while len(lines) < 2:
            lines.append("—")
            kinds.append("idle")
        return ((lines[0], lines[1]), (kinds[0], kinds[1]))

    def _update_station_summary_displays(self) -> None:
        (a, b), kinds = self._mini_overlay_lines_styled()
        if self._config.multi_camera_mode == "stations":
            self._mini_overlay.set_second_line_visible(len(self._config.stations) > 1)
        if self._mini_overlay.isVisible():
            self._mini_overlay.set_lines_styled((a, b), kinds)
        if self._tray is not None:
            self._tray.setToolTip(f"Pack Recorder\n{a}\n{b}")

    def _tick_mini_overlay(self) -> None:
        self._update_station_summary_displays()

    def _sync_mini_overlay_visibility(self) -> None:
        if not self._config.mini_overlay_enabled:
            self._mini_overlay.hide()
            self._mini_overlay_timer.stop()
            return
        if self._config.multi_camera_mode != "stations":
            self._mini_overlay.hide()
            self._mini_overlay_timer.stop()
            return
        minimized = bool(self.windowState() & Qt.WindowState.WindowMinimized)
        hidden = not self.isVisible()
        if minimized or hidden:
            self._update_station_summary_displays()
            self._position_mini_overlay()
            self._mini_overlay.set_click_through(self._config.mini_overlay_click_through)
            self._mini_overlay.show()
            self._mini_overlay.raise_()
            if not self._mini_overlay_timer.isActive():
                self._mini_overlay_timer.start()
        else:
            self._mini_overlay.hide()
            self._mini_overlay_timer.stop()

    def _position_mini_overlay(self) -> None:
        screen = self.screen()
        if screen is None:
            return
        geo = screen.availableGeometry()
        self._mini_overlay.adjustSize()
        sz = self._mini_overlay.sizeHint()
        m = 12
        corner = self._config.mini_overlay_corner
        if corner == "bottom_left":
            x, y = geo.left() + m, geo.bottom() - sz.height() - m
        elif corner == "top_right":
            x, y = geo.right() - sz.width() - m, geo.top() + m
        elif corner == "top_left":
            x, y = geo.left() + m, geo.top() + m
        else:
            x, y = geo.right() - sz.width() - m, geo.bottom() - sz.height() - m
        self._mini_overlay.move(x, y)

    def _restore_from_mini_overlay(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self._mini_overlay.hide()
        self._mini_overlay_timer.stop()

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
            self._update_station_summary_displays()
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
        self._update_station_summary_displays()

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
            if self._is_single_recording_active() and self._recording_started_at.get("single"):
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
            if self._is_single_recording_active():
                for sid, cam in list(self._single_record_cam_by_sid.items()):
                    if cam == cam_idx and self._recorders.get(sid):
                        self._latest_record_bgr[sid] = bgr
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
            for sid, cam in self._single_record_cam_by_sid.items():
                if self._recorders.get(sid):
                    active_record_cams.add(cam)
        else:
            for i, st in enumerate(self._config.stations):
                if self._recorders.get(st.station_id):
                    active_record_cams.add(station_record_cam_id(st, i))
        for cam, w in self._workers.items():
            w.set_recording(cam in active_record_cams)
        self._dual_panel.set_single_station_recording_active(
            self._is_single_recording_active()
        )

    def _on_decoded(self, cam_idx: int, code: str) -> None:
        self._note_user_activity()
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
        if (
            st is None
            and self._config.multi_camera_mode == "stations"
            and self._dual_panel.station_column_count() == 1
            and self._config.stations
        ):
            st0 = self._config.stations[0]
            decode_set: set[int] = {station_record_cam_id(st0, 0)}
            for usb_idx in st0.extra_preview_usb_indices or []:
                ui = int(usb_idx)
                if 0 <= ui <= 9:
                    decode_set.add(ui)
            if int(cam_idx) in decode_set:
                st = st0
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
        self._note_user_activity()
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
        rec_active = (
            self._is_single_recording_active()
            if station_id == "single"
            else self._recorders.get(station_id) is not None
        )
        started_at = self._recording_started_at.get(station_id)
        if rec_active and started_at is not None:
            if (datetime.now() - started_at).total_seconds() < 10.0:
                return
        sm = self._order_sm.get(station_id)
        if sm is None:
            return
        st = self._station_by_id(station_id)
        same_stop = True
        if st is not None:
            # Wedge (keyboard) should behave like dedicated scanner:
            # scan same code again => stop recording.
            same_stop = station_uses_dedicated_barcode_scanner(
                st
            ) or station_uses_keyboard_wedge(st)
        if (
            self._config.multi_camera_mode == "single"
            and station_id == "single"
            and len(
                self._dual_panel.preview_cameras_for_column(
                    0, int(self._config.camera_index)
                )
            )
            > 1
        ):
            same_stop = True
        r = sm.on_scan(
            code,
            is_shutdown_countdown=False,
            same_scan_stops_recording=same_stop,
            now_mono=time.monotonic(),
        )
        if r.should_start_recording and r.new_active_order:
            self._show_station_order_pending(station_id, r.new_active_order)
            self._begin_recording_station(station_id, r.new_active_order)
        if r.should_stop_recording:
            self._stop_recording_after_scan(station_id, r)

    def _begin_recording_station(self, station_id: str, order: str) -> None:
        if self._config.multi_camera_mode == "single" and station_id == "single":
            self._begin_recording_single_station(order)
            return
        st = self._station_by_id(station_id)
        if st is None:
            self._clear_station_order_pending(station_id)
            return
        primary = Path(self._config.video_root)
        bo = (self._config.video_backup_root or "").strip()
        backup = Path(bo) if bo else None
        try:
            write_root, wtag = choose_write_root(primary, backup)
        except OSError as e:
            QMessageBox.warning(self, "Lưu trữ", str(e))
            self._feedback.play_record_start_failed_alert()
            self._order_sm[station_id] = self._new_order_state_machine()
            self._clear_station_order_pending(station_id)
            return
        t0 = datetime.now()
        if is_duplicate_order(write_root, order, t0.date()):
            short = order if len(order) <= 48 else order[:45] + "…"
            self._status.showMessage(
                f"Đã có video cùng mã {short} trong ngày {t0.date().isoformat()} — ghi thêm file mới (tên có giờ phút).",
                6000,
            )
            self._feedback.play_duplicate_order_alert()
        try:
            ff = _resolve_ffmpeg(self._config)
        except FileNotFoundError:
            self._show_ffmpeg_missing_dialog()
            self._feedback.play_record_start_failed_alert()
            self._order_sm[station_id] = self._new_order_state_machine()
            self._clear_station_order_pending(station_id)
            return
        w, h = self._recording_dims_for_station(st)
        fps_out = max(1, min(60, int(self._config.record_fps)))
        out = build_output_path(write_root, order, st.packer_label, t0)
        rel_key = out.relative_to(write_root).as_posix()
        meta = {
            "order": order,
            "packer": st.packer_label,
            "out": out,
            "rel_key": rel_key,
            "tag": wtag,
            "started": t0.isoformat(timespec="seconds"),
        }
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
                self._feedback.play_record_start_failed_alert()
                self._order_sm[station_id] = self._new_order_state_machine()
                self._clear_station_order_pending(station_id)
                return
            self._recorders[station_id] = handle
            self._recording_write_meta[station_id] = meta
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
                self._feedback.play_record_start_failed_alert()
                self._order_sm[station_id] = self._new_order_state_machine()
                self._clear_station_order_pending(station_id)
                return
            self._recorders[station_id] = rec
            self._recording_write_meta[station_id] = meta
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
        self._maybe_tray_toast_order(order)

    def _begin_recording_single_station(self, order: str) -> None:
        station_id = "single"
        st = self._station_by_id(station_id)
        if st is None:
            return
        cams = sorted(
            self._dual_panel.preview_cameras_for_column(
                0, int(self._config.camera_index)
            )
        )
        if not cams:
            cams = [int(self._config.camera_index)]
        primary = Path(self._config.video_root)
        bo = (self._config.video_backup_root or "").strip()
        backup = Path(bo) if bo else None
        try:
            write_root, wtag = choose_write_root(primary, backup)
        except OSError as e:
            QMessageBox.warning(self, "Lưu trữ", str(e))
            self._feedback.play_record_start_failed_alert()
            self._order_sm[station_id] = self._new_order_state_machine()
            self._clear_station_order_pending(station_id)
            return
        t0 = datetime.now()
        if is_duplicate_order(write_root, order, t0.date()):
            short = order if len(order) <= 48 else order[:45] + "…"
            self._status.showMessage(
                f"Đã có video cùng mã {short} trong ngày {t0.date().isoformat()} — ghi thêm file mới (tên có giờ phút).",
                6000,
            )
            self._feedback.play_duplicate_order_alert()
        try:
            ff = _resolve_ffmpeg(self._config)
        except FileNotFoundError:
            self._show_ffmpeg_missing_dialog()
            self._feedback.play_record_start_failed_alert()
            self._order_sm[station_id] = self._new_order_state_machine()
            self._clear_station_order_pending(station_id)
            return
        started_sids: list[str] = []
        try:
            for cam in cams:
                sid = self._single_record_sid(cam)
                pl = self._mp_pipelines.get(cam)
                writer_params = (
                    pl.attach_params_for_writer()
                    if pl is not None and self._config.use_multiprocessing_camera_pipeline
                    else None
                )
                use_subproc_writer = writer_params is not None
                full = self._pip_wh.get(cam)
                if full:
                    w, h = int(full[0]), int(full[1])
                else:
                    w, h = int(self._frame_w), int(self._frame_h)
                fps_out = max(1, min(60, int(self._config.record_fps)))
                out = build_output_path(
                    write_root,
                    order,
                    st.packer_label,
                    t0,
                    suffix=f"cam{cam}",
                )
                rel_key = out.relative_to(write_root).as_posix()
                meta = {
                    "order": order,
                    "packer": st.packer_label,
                    "out": out,
                    "rel_key": rel_key,
                    "tag": wtag,
                    "started": t0.isoformat(timespec="seconds"),
                }
                if use_subproc_writer:
                    assert pl is not None and writer_params is not None
                    shm_name, fw, fh, n_sl, lseq, lslot, llock = writer_params
                    rec = SubprocessRecordingHandle.start_encoder(
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
                            None,
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
                    self._recorders[sid] = rec
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
                    rec.start(out)
                    self._recorders[sid] = rec
                self._single_record_cam_by_sid[sid] = cam
                self._recording_write_meta[sid] = meta
                self._recording_burnin[sid] = RecordingBurnIn(order, st.packer_label, t0)
                self._recording_frame_wh[sid] = (w, h)
                self._recording_emit_fps[sid] = fps_out
                self._recording_next_emit_mono[sid] = time.monotonic()
                self._latest_record_bgr.pop(sid, None)
                started_sids.append(sid)
        except Exception as e:  # noqa: BLE001
            for sid in started_sids:
                rec = self._recorders.get(sid)
                if rec:
                    try:
                        rec.stop()
                    except Exception:
                        pass
                self._recorders[sid] = None
                self._clear_recording_pace_state(sid)
                self._recording_write_meta.pop(sid, None)
                self._single_record_cam_by_sid.pop(sid, None)
            QMessageBox.warning(self, "Không bắt đầu ghi được", str(e))
            self._feedback.play_record_start_failed_alert()
            self._order_sm[station_id] = self._new_order_state_machine()
            self._clear_station_order_pending(station_id)
            return
        self._recording_started_at[station_id] = t0
        self._station_recording_order[station_id] = order
        sm = self._order_sm.get(station_id)
        if sm is not None:
            sm.mark_recording_started(time.monotonic())
        self._ensure_record_pace_timer()
        self._refresh_worker_recording_flags()
        self._chip.setText(f"Đang ghi ({st.packer_label}): {order}")
        self._chip.setStyleSheet(_CHIP_REC_STYLE)
        self._sync_recording_elapsed_timer()
        self._feedback.play_short()
        self._refresh_preview_roi_locks()
        self._maybe_tray_toast_order(order)

    def _begin_recording_pip(self, order: str) -> None:
        primary = Path(self._config.video_root)
        bo = (self._config.video_backup_root or "").strip()
        backup = Path(bo) if bo else None
        try:
            write_root, wtag = choose_write_root(primary, backup)
        except OSError as e:
            QMessageBox.warning(self, "Lưu trữ", str(e))
            self._feedback.play_record_start_failed_alert()
            self._order_sm["pip"] = self._new_order_state_machine()
            return
        t0 = datetime.now()
        if is_duplicate_order(write_root, order, t0.date()):
            short = order if len(order) <= 48 else order[:45] + "…"
            self._status.showMessage(
                f"Đã có video cùng mã {short} trong ngày {t0.date().isoformat()} — ghi thêm file mới (tên có giờ phút).",
                6000,
            )
            self._feedback.play_duplicate_order_alert()
        try:
            ff = _resolve_ffmpeg(self._config)
        except FileNotFoundError:
            self._show_ffmpeg_missing_dialog()
            self._feedback.play_record_start_failed_alert()
            self._order_sm["pip"] = self._new_order_state_machine()
            return
        out = build_output_path(
            write_root, order, self._config.packer_label, t0
        )
        rel_key = out.relative_to(write_root).as_posix()
        meta = {
            "order": order,
            "packer": self._config.packer_label,
            "out": out,
            "rel_key": rel_key,
            "tag": wtag,
            "started": t0.isoformat(timespec="seconds"),
        }
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
            self._feedback.play_record_start_failed_alert()
            self._order_sm["pip"] = self._new_order_state_machine()
            return
        self._recorders["pip"] = rec
        self._recording_write_meta["pip"] = meta
        self._recording_started_at["pip"] = t0
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
        self._maybe_tray_toast_order(order)

    def _stop_recording_for_station(self, station_id: str) -> None:
        if self._config.multi_camera_mode == "single" and station_id == "single":
            self._stop_single_station_recordings()
            return
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
        self._finalize_saved_recording(station_id)
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
        QTimer.singleShot(0, self._refresh_onboarding_banners)

    def _stop_single_station_recordings(self) -> None:
        station_id = "single"
        for sid in list(self._single_recording_sids()):
            self._clear_recording_pace_state(sid)
            rec = self._recorders.get(sid)
            if rec:
                try:
                    rec.stop()
                except Exception:
                    pass
                self._recorders[sid] = None
            self._finalize_saved_recording(sid)
            self._single_record_cam_by_sid.pop(sid, None)
        self._maybe_stop_record_pace_timer()
        self._station_recording_order.pop(station_id, None)
        self._recording_started_at.pop(station_id, None)
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
        if self._config.multi_camera_mode == "single" and station_id == "single":
            self._stop_single_station_recordings()
            self._feedback.play_double()
            sm = self._order_sm.get(station_id)
            if sm is None:
                self._refresh_preview_roi_locks()
                return
            nr = sm.notify_stop_confirmed(now_mono=time.monotonic())
            if nr.should_start_recording and nr.new_active_order:
                self._show_station_order_pending(station_id, nr.new_active_order)
                self._begin_recording_station(station_id, nr.new_active_order)
            else:
                self._chip.setText("Chờ quét mã đơn")
                self._chip.setStyleSheet(_CHIP_IDLE_STYLE)
                self._sync_recording_elapsed_timer()
            self._refresh_preview_roi_locks()
            return
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
        self._finalize_saved_recording(station_id)
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
        nr = sm.notify_stop_confirmed(now_mono=time.monotonic())
        if nr.should_start_recording and nr.new_active_order:
            if self._config.multi_camera_mode == "pip":
                self._begin_recording_pip(nr.new_active_order)
            else:
                self._show_station_order_pending(station_id, nr.new_active_order)
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
        self._note_user_activity()
        p = session_log_path().resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        url = QUrl.fromLocalFile(str(p.parent))
        if not QDesktopServices.openUrl(url):
            QMessageBox.information(
                self,
                "Thư mục log",
                f"Mở thủ công trong Explorer:\n{p.parent}",
            )

    def _launch_wizard_after_settings_closed(self) -> None:
        QTimer.singleShot(0, self._open_setup_wizard)

    def _on_startup_shortcut_hint_recorded(self) -> None:
        if self._config.windows_startup_hint_shown:
            return
        self._config = replace(self._config, windows_startup_hint_shown=True)
        save_config(self._config_path, self._config)

    def _on_test_notification(self, source: str) -> None:
        """Thử phát âm / khay từ Cài đặt — không lưu dialog; không đổi sound_mode đã lưu."""
        try:
            self._note_user_activity()
            if source == "tray":
                if self._tray is not None:
                    self._tray.showMessage(
                        "Pack Recorder",
                        "Thử thông báo khay",
                        QSystemTrayIcon.MessageIcon.Information,
                        4000,
                    )
                else:
                    self._status.showMessage(
                        "Thử thông báo khay — bật «Thu vào khay hệ thống» để có icon khay.",
                        6000,
                    )
                return
            if source in ("speaker", "scanner_host"):
                self._feedback.play_test_short_for_mode(source)
        except Exception:
            import sys

            log_session_error(
                "Lỗi trong _on_test_notification (thử âm / khay).",
                exc_info=sys.exc_info(),
            )

    def _open_settings(self) -> None:
        self._note_user_activity()
        if any(r is not None for r in self._recorders.values()):
            QMessageBox.warning(
                self,
                "Đang ghi hình",
                "Vui lòng dừng ghi (quét lại cùng mã đơn hoặc đóng phiên) trước khi mở Cài đặt.",
            )
            return
        self._pause_scan_workers()
        dlg = SettingsDialog(
            self._config,
            self,
            on_test_notification=self._on_test_notification,
            on_run_setup_wizard=self._launch_wizard_after_settings_closed,
            on_startup_shortcut_created=self._on_startup_shortcut_hint_recorded,
        )
        try:
            if dlg.exec():
                self._config = dlg.result_config()
                ensure_stations_layout(self._config)
                self._config = normalize_config(self._config)
                save_config(self._config_path, self._config)
                self._feedback.update_config(self._config)
                self._heartbeat_timer.setInterval(
                    max(5_000, int(self._config.heartbeat_interval_ms))
                )
                self._restart_office_heartbeat_timer()
                if self._sync_worker is not None:
                    self._sync_worker.stop_worker()
                    self._sync_worker.wait(4000)
                    self._sync_worker = None
                self._close_recording_index()
                self._try_open_recording_index()
                self._restart_sync_worker()
                self._refresh_next_shutdown()
                self._rebuild_order_machines()
                self._update_packer_message()
                self._update_central_page()
                self._dual_panel.set_kiosk_mode(self._kiosk_counter_ui())
                self._sync_record_resolution_combo_from_config()
                self._sync_always_on_top_from_config()
                self._sync_header_video_root_from_config()
                self._sync_footer_controls_from_config()
                self._setup_system_tray()
                self._restart_tray_health_timer()
                self._mini_overlay.set_click_through(self._config.mini_overlay_click_through)
                if not self._config.mini_overlay_enabled:
                    self._mini_overlay.hide()
                    self._mini_overlay_timer.stop()
                self._sync_mini_overlay_visibility()
                qa = QApplication.instance()
                if qa is not None:
                    tray_ok = self._config.minimize_to_tray and self._tray is not None
                    qa.setQuitOnLastWindowClosed(not tray_ok)
                QTimer.singleShot(0, self._refresh_onboarding_banners)
        finally:
            self._restart_scan_workers()

    def _open_setup_wizard(self) -> None:
        self._note_user_activity()
        if any(r is not None for r in self._recorders.values()):
            QMessageBox.warning(
                self,
                "Đang ghi hình",
                "Vui lòng dừng ghi trước khi mở thiết lập quầy.",
            )
            return
        self._pause_scan_workers()
        try:
            from packrecorder.ui.setup_wizard import SetupWizardDialog

            dlg = SetupWizardDialog(self._config, self)
            if dlg.exec():
                self._config = dlg.result_config()
                ensure_stations_layout(self._config)
                self._config = normalize_config(self._config)
                save_config(self._config_path, self._config)
                self._feedback.update_config(self._config)
                self._heartbeat_timer.setInterval(
                    max(5_000, int(self._config.heartbeat_interval_ms))
                )
                self._restart_office_heartbeat_timer()
                if self._sync_worker is not None:
                    self._sync_worker.stop_worker()
                    self._sync_worker.wait(4000)
                    self._sync_worker = None
                self._close_recording_index()
                self._try_open_recording_index()
                self._restart_sync_worker()
                self._refresh_next_shutdown()
                self._rebuild_order_machines()
                self._update_packer_message()
                # Kiosk + đồng bộ UI: _update_central_page đã gọi sync_from_config nhẹ
                # (probed_override=[], fast_serial_scan) và lên lịch probe nền — không gọi lại
                # sync_from_config đầy đủ ở đây (probe camera + mở từng COM) vì treo UI sau wizard.
                self._dual_panel.set_kiosk_mode(self._kiosk_counter_ui())
                self._update_central_page()
                self._sync_record_resolution_combo_from_config()
                self._sync_always_on_top_from_config()
                self._sync_header_video_root_from_config()
                self._sync_footer_controls_from_config()
                self._setup_system_tray()
                self._restart_tray_health_timer()
                qa = QApplication.instance()
                if qa is not None:
                    tray_ok = self._config.minimize_to_tray and self._tray is not None
                    qa.setQuitOnLastWindowClosed(not tray_ok)
                QTimer.singleShot(0, self._refresh_onboarding_banners)
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
            self._sync_mini_overlay_visibility()
            st = self.windowState()
            if bool(st & Qt.WindowState.WindowMinimized) and (
                self._config.multi_camera_mode == "stations"
            ):
                try:
                    a, b = self._mini_overlay_line_pair()
                    self.setWindowTitle(format_minimized_window_title(a, b))
                except Exception:
                    self.setWindowTitle("Pack Recorder")
            elif not bool(st & Qt.WindowState.WindowMinimized):
                self.setWindowTitle("Pack Recorder")
        super().changeEvent(event)

    def hideEvent(self, event: QHideEvent) -> None:  # noqa: N802
        super().hideEvent(event)
        self._sync_mini_overlay_visibility()

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._mini_overlay.isVisible():
            self._position_mini_overlay()

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Escape and self.isFullScreen():
            r = QMessageBox.question(
                self,
                "Thoát toàn màn hình",
                "Thoát chế độ toàn màn hình?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if r == QMessageBox.StandardButton.Yes:
                self.showNormal()
            event.accept()
            return
        super().keyPressEvent(event)

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._shutdown_done:
            super().closeEvent(event)
            return
        if self._config.minimize_to_tray and self._config.close_to_tray:
            if self._tray is None:
                self._shutdown_application(reason="close_event_no_tray")
                event.accept()
                super().closeEvent(event)
                return
            event.ignore()
            self.hide()
            self._sync_mini_overlay_visibility()
            self._tray.showMessage(
                "Pack Recorder",
                "Ứng dụng vẫn chạy nền. Mở lại từ biểu tượng khay hệ thống.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )
            return
        self._shutdown_application(reason="close_event_default")
        super().closeEvent(event)
