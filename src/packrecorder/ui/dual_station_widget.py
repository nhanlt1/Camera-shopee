from __future__ import annotations

import sys
from dataclasses import replace
from typing import Optional

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStyle,
    QToolButton,
    QVBoxLayout,
    QWidget,
    QStackedWidget,
)

from packrecorder.camera_probe import probe_opencv_camera_indices
from packrecorder.config import AppConfig, StationConfig, is_rtsp_stream_url
from packrecorder.hid_scanner_discovery import (
    HID_POS_USAGE_PAGE,
    device_label,
    enumerate_hid_or_error,
    filter_scanner_candidates,
    list_usage_page_devices,
    vid_pid_int_from_device,
)
from packrecorder.session_log import log_session_error
from packrecorder.order_input import normalize_manual_order_text
from packrecorder.serial_ports import (
    choose_serial_port,
    iter_raw_comports,
    list_filtered_serial_ports,
    vid_pid_by_device,
)
from packrecorder.ui.hid_pos_setup_wizard import HidPosSetupWizard
from packrecorder.ui.camera_preview import bgr_bytes_to_pixmap
from packrecorder.ui.roi_preview_label import RoiPreviewLabel
from packrecorder.ui.scanner_mode_dialog import ScannerModeDialog

# Giống placeholder: khi chọn RTSP lần đầu (ô trống), điền sẵn để sửa ngay, không phải gõ lại từng ký tự.
RTSP_DEFAULT_URL_TEXT_1 = (
    "rtsp://admin:Abcd1234@192.168.100.230:554/cam/realmonitor?channel=1&subtype=1"
)
RTSP_DEFAULT_URL_TEXT_2 = (
    "rtsp://admin:Abcd1234@192.168.100.247:554/cam/realmonitor?channel=1&subtype=1"
)

RTSP_DEFAULT_URL_BY_COLUMN = (RTSP_DEFAULT_URL_TEXT_1, RTSP_DEFAULT_URL_TEXT_2)


def _station_camera_indices(stations: list[StationConfig]) -> set[int]:
    """Index camera đang dùng trong cấu hình (luôn đưa vào combo dù probe không thấy)."""
    out: set[int] = set()
    for idx, s in enumerate(stations[:2]):
        if s.record_camera_kind == "rtsp" and is_rtsp_stream_url(s.record_rtsp_url):
            continue
        out.add(int(s.record_camera_index))
        out.add(int(s.decode_camera_index))
    return out


def _merge_probe_with_config(probed: list[int], cfg: AppConfig) -> list[int]:
    base = set(probed) if probed else {0}
    base |= _station_camera_indices(list(cfg.stations))
    return sorted(base)


def _normalize_usb_indices(indices: list[int]) -> list[int]:
    out: list[int] = []
    for raw in indices:
        try:
            cam = int(raw)
        except (TypeError, ValueError):
            continue
        if 0 <= cam <= 9 and cam not in out:
            out.append(cam)
    return out[:8]


class DualStationWidget(QWidget):
    """Hai cột: camera ghi, máy quét COM (USB serial), hoặc camera đọc mã."""

    _BANNER_TEXT_STYLE = (
        "background-color:#fde7e9;color:#8f0804;padding:6px 10px;"
        "font-size:12px;font-weight:bold;border-radius:8px;border:1px solid #c42b1c;"
        "font-family:'Cascadia Mono',Consolas,'Segoe UI Variable','Segoe UI',sans-serif;"
    )
    _PENDING_ORDER_BANNER_STYLE = (
        "background-color:#fde7e9;color:#6a0a0a;padding:8px 12px;"
        "font-size:13px;font-weight:bold;border-radius:8px;border:1px solid #c42b1c;"
        "font-family:'Cascadia Mono',Consolas,'Segoe UI Variable','Segoe UI',sans-serif;"
    )

    fields_changed = Signal()
    refresh_devices_requested = Signal()
    manual_order_submitted = Signal(int, str)
    rtsp_connect_requested = Signal(int, str)

    def __init__(self, parent=None, *, kiosk_mode: bool = False) -> None:
        super().__init__(parent)
        self._cinema_mode = False
        self._kiosk_mode = bool(kiosk_mode)
        self._cam_indices: list[int] = [0, 1]
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(320)
        self._debounce.timeout.connect(self.fields_changed.emit)

        self._root = QLineEdit()
        self._root.setPlaceholderText("Thư mục lưu video…")
        self._root.setVisible(False)
        self._root.editingFinished.connect(self._emit_debounced)

        btn_refresh = QPushButton("Làm mới thiết bị")
        btn_refresh.setToolTip(
            "Quét lại webcam và thiết bị máy quét đang cắm."
        )
        btn_refresh.setMinimumHeight(32)
        self._btn_refresh = btn_refresh
        btn_refresh.clicked.connect(self._on_refresh_clicked)

        self._top_bar = QWidget()
        top = QVBoxLayout(self._top_bar)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(0)
        top.addWidget(self._root)

        self._preview: list[RoiPreviewLabel] = []
        self._record_banner: list[QLabel] = []
        self._record_elapsed: list[QLabel] = []
        self._group_boxes: list[QGroupBox] = []
        self._column_forms: list[QWidget] = []
        self._record: list[QComboBox] = []
        self._record_kind: list[QButtonGroup] = []
        self._rtsp_url: list[QLineEdit] = []
        self._rtsp_connect_btn: list[QPushButton] = []
        self._rtsp_armed: list[bool] = [False, False]
        self._scanner: list[QComboBox] = []
        self._scanner_input_kind: list[QComboBox] = []
        self._hid_vid: list[QLineEdit] = []
        self._hid_pid: list[QLineEdit] = []
        self._scanner_match_hint: list[QLabel] = []
        self._decode_hint: list[QLabel] = []
        self._name: list[QLineEdit] = []
        self._manual_col_order: list[QLineEdit] = []
        self._scanner_expected_vid_pid: list[tuple[str, str]] = [("", ""), ("", "")]
        self._scanner_com_only: bool = True
        self._hid_row_widget: list[QWidget] = []
        self._hid_block_widget: list[QWidget] = []
        self._hid_device_combo: list[QComboBox] = []
        self._hid_usage_label: list[QLabel] = []
        self._scanner_selected_label: list[QLabel] = []
        self._tl_scan: list[QLabel] = []
        self._adv_btn: list[QToolButton] = []
        self._station_column_count = 2
        self._single_watch_indices: list[int] = []
        self._single_focus_camera: int | None = None
        self._single_recording_active: bool = False
        self._single_view_mode: str = "focus"
        self._single_frames: dict[int, tuple[bytes, int, int]] = {}
        self._single_toolbar_wrap: QWidget | None = None
        self._single_camera_btn_row: QHBoxLayout | None = None
        self._single_mode_toggle_btn: QToolButton | None = None
        self._single_preview_stack: QStackedWidget | None = None
        self._single_grid_area: QScrollArea | None = None
        self._single_grid_wrap: QWidget | None = None
        self._single_grid_layout: QGridLayout | None = None
        self._single_grid_labels: dict[int, QLabel] = {}

        columns = QHBoxLayout()
        for col in range(2):
            box = QGroupBox(f"Máy {col + 1}")
            self._group_boxes.append(box)
            v = QVBoxLayout(box)
            banner = QLabel()
            banner.setVisible(False)
            banner.setWordWrap(False)
            banner.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
                | Qt.TextInteractionFlag.TextSelectableByKeyboard
            )
            banner.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            banner.setStyleSheet(DualStationWidget._BANNER_TEXT_STYLE)
            self._record_banner.append(banner)
            v.addWidget(banner, 0)

            elapsed = QLabel()
            elapsed.setVisible(False)
            elapsed.setAlignment(Qt.AlignmentFlag.AlignCenter)
            elapsed.setWordWrap(False)
            elapsed.setStyleSheet(
                "background-color:#fde7e9;color:#8f0804;padding:6px 8px;"
                "font-size:12px;font-weight:bold;border-radius:8px;"
                "font-family:'Cascadia Mono',Consolas,'Segoe UI Mono',monospace;"
                "border:1px solid #c42b1c;"
            )
            self._record_elapsed.append(elapsed)
            v.addWidget(elapsed, 0)

            row_m = QHBoxLayout()
            row_m.setContentsMargins(0, 4, 0, 0)
            row_m.setSpacing(8)
            mo = QLineEdit()
            mo.setPlaceholderText(
                f"Máy {col + 1}: nhập mã thủ công và bấm nút «Bắt đầu ghi». "
                "COM: quét lặp cùng mã → dừng. Camera: đổi mã mới mới dừng/chuyển đơn."
            )
            mo.setMinimumHeight(28)
            mo.returnPressed.connect(
                lambda c=col: self._emit_manual_col(c, source="enter")
            )
            btn_m = QPushButton("Bắt đầu ghi")
            btn_m.setToolTip(
                "Gửi mã đơn cho quầy này — cùng luồng với máy quét / camera đọc mã."
            )
            btn_m.clicked.connect(
                lambda _checked=False, c=col: self._emit_manual_col(c, source="button")
            )
            lab_mo = QLabel("Mã đơn:")
            lab_mo.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed,
            )
            row_m.addWidget(lab_mo, 0)
            mo.setSizePolicy(
                QSizePolicy.Policy.Expanding,
                QSizePolicy.Policy.Fixed,
            )
            btn_m.setSizePolicy(
                QSizePolicy.Policy.Fixed,
                QSizePolicy.Policy.Fixed,
            )
            row_m.addWidget(mo, 1)
            row_m.addWidget(btn_m, 0)
            order_row_w = QWidget()
            order_row_w.setLayout(row_m)
            self._manual_col_order.append(mo)
            v.addWidget(order_row_w, 0)

            prev = RoiPreviewLabel()
            prev.roi_changed.connect(self._emit_debounced)
            self._preview.append(prev)
            if col == 0:
                self._single_preview_stack = QStackedWidget()
                self._single_preview_stack.addWidget(prev)
                self._single_toolbar_wrap = QWidget()
                single_tools = QVBoxLayout(self._single_toolbar_wrap)
                single_tools.setContentsMargins(0, 6, 0, 0)
                single_tools.setSpacing(6)
                row_tools = QHBoxLayout()
                row_tools.setContentsMargins(0, 0, 0, 0)
                row_tools.setSpacing(6)
                btn_mode_toggle = QToolButton()
                btn_mode_toggle.clicked.connect(self._toggle_single_view_mode)
                btn_add = QToolButton()
                btn_add.setText("+ Thêm camera")
                btn_add.clicked.connect(self._on_add_single_preview_camera_clicked)
                row_tools.addWidget(btn_mode_toggle)
                row_tools.addWidget(btn_add)
                row_tools.addStretch(1)
                single_tools.addLayout(row_tools)
                cams_row = QHBoxLayout()
                cams_row.setContentsMargins(0, 0, 0, 0)
                cams_row.setSpacing(6)
                self._single_camera_btn_row = cams_row
                single_tools.addLayout(cams_row)
                self._single_mode_toggle_btn = btn_mode_toggle
                self._single_grid_area = QScrollArea()
                self._single_grid_area.setWidgetResizable(True)
                self._single_grid_wrap = QWidget()
                self._single_grid_layout = QGridLayout(self._single_grid_wrap)
                self._single_grid_layout.setContentsMargins(0, 0, 0, 0)
                self._single_grid_layout.setSpacing(8)
                self._single_grid_area.setWidget(self._single_grid_wrap)
                self._single_preview_stack.addWidget(self._single_grid_area)
                v.addWidget(self._single_preview_stack, 1)
                v.addWidget(self._single_toolbar_wrap, 0)
            else:
                v.addWidget(prev, 1)

            form_w = QWidget()
            form_l = QVBoxLayout(form_w)
            form_l.setContentsMargins(0, 0, 0, 0)
            self._column_forms.append(form_w)

            ne = QLineEdit()
            ne.setPlaceholderText(f"Máy {col + 1}")
            ne.editingFinished.connect(lambda _c=col: self._on_station_name_finished())

            tl_name = QLabel("Tên máy")
            tl_name.setToolTip("Nhãn hiển thị trên video và trong thư mục lưu file.")

            kind_box = QHBoxLayout()
            rb_usb = QRadioButton("USB (webcam)")
            rb_rtsp = QRadioButton("RTSP (IP)")
            rb_usb.setChecked(True)
            bg = QButtonGroup(self)
            bg.addButton(rb_usb, 0)
            bg.addButton(rb_rtsp, 1)
            self._record_kind.append(bg)
            kind_box.addWidget(rb_usb)
            kind_box.addWidget(rb_rtsp)
            kind_box.addStretch(1)
            kind_w = QWidget()
            kind_w.setLayout(kind_box)

            adv_btn = QToolButton()
            adv_btn.setText("Nâng cao")
            adv_btn.setToolTip(
                "Mở thêm: chọn RTSP (IP) và chỉnh vùng ROI đọc mã trên preview."
            )
            adv_btn.setCheckable(True)
            adv_btn.setChecked(False)
            adv_btn.setAutoRaise(True)
            kind_row = QHBoxLayout()
            kind_row.setContentsMargins(0, 0, 0, 0)
            kind_row.addWidget(kind_w, 1)
            kind_row.addWidget(adv_btn, 0, Qt.AlignmentFlag.AlignTop)
            kind_row_w = QWidget()
            kind_row_w.setLayout(kind_row)
            self._adv_btn.append(adv_btn)
            adv_btn.toggled.connect(
                lambda checked, c=col: self._on_advanced_toggled(c, checked)
            )

            tl_cam = QLabel("Camera ghi (mã nguồn)")
            tl_cam.setToolTip(
                "USB: webcam chỉ số. RTSP: URL đầy đời (có thể sửa trong file config.json). "
                "Một nguồn cho xem trước, ghi và đọc mã (pyzbar) khi không dùng COM."
            )

            cam_stack = QVBoxLayout()
            cam_stack.setContentsMargins(0, 0, 0, 0)
            rc = QComboBox()
            rc.setMinimumWidth(200)
            rc.currentIndexChanged.connect(lambda _i, c=col: self._on_record_changed(c))
            cam_stack.addWidget(rc)
            rtsp = QLineEdit()
            rtsp.setPlaceholderText(RTSP_DEFAULT_URL_BY_COLUMN[col])
            rtsp.setVisible(False)
            rtsp.setToolTip(
                "Dahua/KBVision: subtype=1 thường là luồng phụ (nhẹ hơn). "
                "Có thể chỉnh URL trong %LOCALAPPDATA%\\PackRecorder\\config.json.\n"
                "Nếu không kết nối được, app không chặn vô hạn — có thể chỉnh biến môi trường "
                "PACKRECORDER_RTSP_OPEN_TIMEOUT_MS / PACKRECORDER_RTSP_READ_TIMEOUT_MS (mặc định 8000/5000)."
            )
            rtsp.editingFinished.connect(lambda c=col: self._on_rtsp_text_changed(c))
            rtsp.textChanged.connect(lambda _t, c=col: self._on_rtsp_text_changed(c))
            cam_stack.addWidget(rtsp)
            self._rtsp_url.append(rtsp)
            btn_rtsp = QPushButton("Kết nối RTSP")
            btn_rtsp.setToolTip(
                "Chỉ sau khi bấm nút này app mới lưu cấu hình RTSP và mở luồng — "
                "chọn USB thì không kích hoạt RTSP. Sửa URL: cần bấm lại để áp dụng."
            )
            btn_rtsp.setVisible(False)
            btn_rtsp.clicked.connect(
                lambda _checked=False, c=col: self._on_rtsp_connect_clicked(c)
            )
            cam_stack.addWidget(btn_rtsp)
            self._rtsp_connect_btn.append(btn_rtsp)
            cw = QWidget()
            cw.setLayout(cam_stack)
            self._record.append(rc)
            bg.idClicked.connect(lambda _id, c=col: self._on_record_kind_changed(c))

            sc = QComboBox()
            sc.setMinimumWidth(200)
            sc.setMinimumHeight(34)
            sc.setToolTip(
                "Chọn đúng máy quét: đọc cả dòng mô tả, không chỉ COMx. "
                "Ưu tiên cổng USB serial (thường lên đầu danh sách)."
            )
            sc.currentIndexChanged.connect(lambda _i, c=col: self._on_scanner_or_decode_changed(c))
            self._scanner.append(sc)

            sk = QComboBox()
            sk.setMinimumWidth(200)
            sk.setMinimumHeight(34)
            sk.addItem("USB–COM", "com")
            sk.addItem("HID POS (VID/PID)", "hid_pos")
            sk.setToolTip(
                "USB–COM: máy quét dạng serial (cổng COM). "
                "HID POS: đọc raw qua hidapi — chỉ cần VID/PID (pip: hidapi, kèm DLL Windows). "
                "Ẩn cửa sổ / icon khay bật trong Tệp → Cài đặt → Khay hệ thống."
            )
            sk.currentIndexChanged.connect(
                lambda _i, c=col: self._on_scanner_input_kind_changed(c)
            )
            self._scanner_input_kind.append(sk)

            hv = QLineEdit()
            hv.setPlaceholderText("VID (HEX 4)")
            hv.setMaxLength(4)
            hv.textChanged.connect(lambda _t, c=col: self._emit_debounced())
            hv.textChanged.connect(lambda _t, c=col: self._on_hid_vid_pid_changed(c))
            hp = QLineEdit()
            hp.setPlaceholderText("PID (HEX 4)")
            hp.setMaxLength(4)
            hp.textChanged.connect(lambda _t, c=col: self._emit_debounced())
            hp.textChanged.connect(lambda _t, c=col: self._on_hid_vid_pid_changed(c))
            self._hid_vid.append(hv)
            self._hid_pid.append(hp)

            tl_scan = QLabel("Máy quét (USB–COM)")
            tl_scan.setToolTip(
                "Mỗi cổng hiển thị tên thiết bị (Windows) + hãng + mã VID:PID khi có — "
                "bấm «Làm mới camera & cổng COM» để quét lại sau khi cắm máy quét.\n"
                "Tốc độ Baud dùng mặc định trong cấu hình (thường 9600); cần khác thì chỉnh trong "
                "tệp cấu hình JSON (không hiện nút trên UI để tránh chỉnh nhầm)."
            )
            self._tl_scan.append(tl_scan)

            row_controls = QHBoxLayout()
            row_controls.setSpacing(12)
            v_cam = QVBoxLayout()
            v_cam.setSpacing(4)
            v_cam.setContentsMargins(0, 0, 0, 0)
            v_cam.addWidget(tl_name)
            v_cam.addWidget(ne)
            v_cam.addWidget(tl_cam)
            v_cam.addWidget(kind_row_w)
            v_cam.addWidget(cw)
            w_cam = QWidget()
            w_cam.setLayout(v_cam)
            row_controls.addWidget(w_cam, 1)

            v_scan = QVBoxLayout()
            v_scan.setSpacing(4)
            v_scan.setContentsMargins(0, 0, 0, 0)
            v_scan.addWidget(QLabel("Kiểu máy quét"))
            v_scan.addWidget(sk)
            v_scan.addWidget(tl_scan)
            v_scan.addWidget(sc)
            selected_scanner = QLabel("Máy quét đã chọn: chưa có")
            selected_scanner.setStyleSheet(
                "color:#605e5c;font-size:12px;font-family:'Segoe UI Variable','Segoe UI',sans-serif;"
            )
            selected_scanner.setWordWrap(True)
            self._scanner_selected_label.append(selected_scanner)
            v_scan.addWidget(selected_scanner)
            hid_row = QHBoxLayout()
            hid_row.setSpacing(8)
            hid_row.addWidget(hv, 1)
            hid_row.addWidget(hp, 1)
            hid_w = QWidget()
            hid_w.setLayout(hid_row)
            hid_w.setVisible(False)
            self._hid_row_widget.append(hid_w)

            hid_tool_row = QHBoxLayout()
            hid_tool_row.setSpacing(8)
            hcb = QComboBox()
            hcb.setMinimumWidth(160)
            hcb.setMinimumHeight(34)
            hcb.setToolTip(
                "Danh sách thiết bị HID gần giống máy quét (tên / Usage Page 0x8C). "
                "Chọn một mục để điền VID/PID — hoặc nhập tay bên dưới."
            )
            hcb.currentIndexChanged.connect(
                lambda _i, c=col: self._on_hid_device_combo_changed(c)
            )
            btn_hid_refresh = QPushButton("Làm mới HID")
            btn_hid_refresh.setToolTip("Quét lại danh sách thiết bị HID (cần cài packrecorder[hid]).")
            btn_hid_refresh.setMinimumHeight(34)
            btn_hid_refresh.clicked.connect(
                lambda _checked=False, c=col: self._on_hid_refresh_clicked(c)
            )
            btn_hid_wizard = QPushButton("Tự phát hiện máy quét")
            btn_hid_wizard.setToolTip("Hướng dẫn từng bước: rút/cắm USB và chọn đúng máy quét.")
            btn_hid_wizard.setMinimumHeight(34)
            btn_hid_wizard.clicked.connect(
                lambda _checked=False, c=col: self._open_hid_wizard(c)
            )
            hid_tool_row.addWidget(hcb, 1)
            hid_tool_row.addWidget(btn_hid_refresh)
            hid_tool_row.addWidget(btn_hid_wizard)
            btn_mode_settings = QPushButton("⚙ Cài đặt")
            btn_mode_settings.setIcon(
                self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
            )
            btn_mode_settings.setToolTip("Cài đặt máy quét")
            btn_mode_settings.setMinimumHeight(34)
            btn_mode_settings.setStyleSheet(
                "font-weight:600;padding:4px 10px;"
            )
            btn_mode_settings.clicked.connect(
                lambda _checked=False, c=col: self._open_scanner_mode_dialog(c)
            )
            hid_tool_row.addWidget(btn_mode_settings)
            hid_tool_w = QWidget()
            hid_tool_w.setLayout(hid_tool_row)
            h_usage = QLabel("")
            h_usage.setWordWrap(True)
            h_usage.setStyleSheet(
                "color:#0067c0;font-size:11px;font-family:'Segoe UI Variable','Segoe UI',sans-serif;"
            )
            h_usage.setVisible(False)
            hid_block = QWidget()
            hid_block_l = QVBoxLayout(hid_block)
            hid_block_l.setContentsMargins(0, 0, 0, 0)
            hid_block_l.setSpacing(4)
            hid_block_l.addWidget(hid_tool_w)
            hid_block_l.addWidget(h_usage)
            v_scan.addWidget(hid_block)
            self._hid_block_widget.append(hid_block)
            self._hid_device_combo.append(hcb)
            self._hid_usage_label.append(h_usage)

            sh = QLabel("")
            sh.setStyleSheet(
                "color:#107c10;font-size:11px;font-family:'Segoe UI Variable','Segoe UI',sans-serif;"
            )
            sh.setWordWrap(True)
            sh.setVisible(False)
            self._scanner_match_hint.append(sh)
            v_scan.addWidget(sh)
            w_scan = QWidget()
            w_scan.setLayout(v_scan)
            row_controls.addWidget(w_scan, 1)

            self._name.append(ne)

            dh = QLabel("")
            dh.setWordWrap(True)
            dh.setStyleSheet(
                "color:#605e5c;font-size:11px;font-family:'Segoe UI Variable','Segoe UI',sans-serif;"
            )
            self._decode_hint.append(dh)
            form_l.addLayout(row_controls)

            v.addWidget(form_w, 0)
            columns.addWidget(box, 1)

        root_layout = QVBoxLayout(self)
        root_layout.addWidget(self._top_bar, 0)
        root_layout.addLayout(columns, 1)
        self._refresh_layout_mode()
        for c in range(2):
            self._apply_advanced_visibility(c, False)

    def set_station_column_count(self, n: int) -> None:
        """1 hoặc 2 — ẩn hoàn toàn cột quầy dư (một quầy = một cột)."""
        self._station_column_count = max(1, min(2, int(n)))
        for i, box in enumerate(self._group_boxes):
            box.setVisible(i < self._station_column_count)
        self._refresh_layout_mode()

    def station_column_count(self) -> int:
        return int(self._station_column_count)

    def single_station_roi_should_lock(self) -> bool:
        """Khóa kéo ROI khi đang xem camera phụ (không phải camera ghi USB)."""
        if self._station_column_count != 1:
            return False
        if self._is_rtsp_column(0):
            return False
        if self._single_view_mode == "grid":
            return True
        rec = int(self._record[0].currentData() or 0)
        return self._effective_focus_camera(rec) != rec

    def set_kiosk_mode(self, on: bool) -> None:
        """Quầy hằng ngày: ẩn form thiết bị; chi tiết qua Wizard / Cài đặt."""
        on = bool(on)
        if self._kiosk_mode == on:
            return
        self._kiosk_mode = on
        self._refresh_layout_mode()

    def _refresh_layout_mode(self) -> None:
        """Đồng bộ cinema + kiosk: ẩn khối cấu hình thiết bị khi cần."""
        hide_device = self._cinema_mode or self._kiosk_mode
        self._top_bar.setVisible(not self._cinema_mode)
        for fw in self._column_forms:
            fw.setVisible(not hide_device)
        for i, box in enumerate(self._group_boxes):
            box.setFlat(self._cinema_mode)
            if self._cinema_mode:
                box.setTitle("")
            elif self._kiosk_mode and i < len(self._name):
                nm = (self._name[i].text() or "").strip() or f"Máy {i + 1}"
                box.setTitle(nm)
            else:
                box.setTitle(f"Máy {i + 1}")
        for prev in self._preview:
            prev.set_fast_scale(not self._cinema_mode)
            if self._cinema_mode:
                prev.setMinimumSize(240, 180)
                prev.setMaximumHeight(16_777_215)
                prev.setSizePolicy(
                    QSizePolicy.Policy.Expanding,
                    QSizePolicy.Policy.Expanding,
                )
            else:
                # Cửa sổ thường: preview chiếm phần dọc còn lại (không giới hạn 280px —
                # tránh khoảng trống lớn và video không scale khi kéo cao cửa sổ).
                prev.setMinimumSize(280, 160)
                prev.setMaximumHeight(16_777_215)
                prev.setSizePolicy(
                    QSizePolicy.Policy.Expanding,
                    QSizePolicy.Policy.Expanding,
                )
        self._refresh_single_station_preview_mode_ui()

    def _single_watch_camera_set(self, record_cam: int) -> list[int]:
        out: list[int] = [int(record_cam)]
        for cam in self._single_watch_indices:
            if cam not in out:
                out.append(int(cam))
        return out

    def _rebuild_single_camera_buttons(self, record_cam: int) -> None:
        row = self._single_camera_btn_row
        if row is None:
            return
        watched_cams = self._single_watch_camera_set(record_cam)
        can_remove_camera = (len(watched_cams) > 1) and (not self._single_recording_active)
        while row.count():
            it = row.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        for cam in watched_cams:
            btn = QToolButton()
            btn.setText(f"Cam {cam}")
            btn.setCheckable(True)
            btn.setChecked(self._effective_focus_camera(record_cam) == cam)
            btn.setStyleSheet(
                "QToolButton {"
                " border: 1px solid #8a8886;"
                " border-radius: 10px;"
                " padding: 4px 10px;"
                " background: #f3f2f1;"
                " color: #323130;"
                "}"
                "QToolButton:hover {"
                " border-color: #605e5c;"
                " background: #edebe9;"
                "}"
                "QToolButton:checked {"
                " border-color: #0078d4;"
                " background: #deecf9;"
                " color: #004578;"
                " font-weight: 600;"
                "}"
            )
            btn.clicked.connect(lambda _checked=False, c=cam: self._set_single_focus_camera(c))
            wrap = QWidget()
            wrap.setObjectName("camChipWrap")
            wrap.setStyleSheet(
                "QWidget#camChipWrap {"
                " border: 1px solid #8a8886;"
                " border-radius: 10px;"
                " background: #f3f2f1;"
                "}"
                "QWidget#camChipWrap:disabled {"
                " border-color: #d2d0ce;"
                " background: #f3f2f1;"
                "}"
            )
            h = QHBoxLayout(wrap)
            h.setContentsMargins(8, 1, 4, 1)
            h.setSpacing(2)
            btn.setStyleSheet(
                "QToolButton {"
                " border: none;"
                " padding: 2px 2px;"
                " background: transparent;"
                " color: #323130;"
                "}"
                "QToolButton:checked {"
                " color: #004578;"
                " font-weight: 600;"
                "}"
            )
            btn_remove = QToolButton()
            btn_remove.setText("X")
            btn_remove.setToolTip("Xóa camera phụ khỏi danh sách xem")
            btn_remove.setEnabled(can_remove_camera)
            btn_remove.setStyleSheet(
                "QToolButton {"
                " color: #a80000;"
                " border: none;"
                " min-width: 18px;"
                " min-height: 18px;"
                " max-width: 18px;"
                " max-height: 18px;"
                " padding: 0px;"
                " background: transparent;"
                " font-weight: 700;"
                "}"
                "QToolButton:hover {"
                " color: #ffffff;"
                " background: #c50f1f;"
                " border-radius: 9px;"
                "}"
                "QToolButton:disabled {"
                " color: #b3b0ad;"
                " background: transparent;"
                "}"
            )
            btn_remove.clicked.connect(
                lambda _checked=False, c=cam: self._remove_single_watch_camera(c)
            )
            h.addWidget(btn)
            h.addWidget(btn_remove)
            row.addWidget(wrap)
        row.addStretch(1)

    def _remove_single_watch_camera(self, cam: int) -> None:
        if self._single_recording_active:
            return
        cam_i = int(cam)
        record_cam = int(self._record[0].currentData() or 0)
        watched = self._single_watch_camera_set(record_cam)
        if cam_i not in watched:
            return
        if len(watched) <= 1:
            return
        if cam_i == record_cam:
            replacement = next((c for c in watched if c != cam_i), None)
            if replacement is None:
                return
            # Cam gốc bị xóa: chọn cam còn lại làm cam gốc mới.
            self._single_watch_indices = [
                i for i in self._single_watch_indices if i != cam_i and i != replacement
            ]
            if self._single_focus_camera == cam_i:
                self._single_focus_camera = None
            idx = self._record[0].findData(int(replacement))
            if idx >= 0:
                self._record[0].setCurrentIndex(idx)
            else:
                self._repopulate_record_combo(0, int(replacement))
                idx = self._record[0].findData(int(replacement))
                if idx >= 0:
                    self._record[0].setCurrentIndex(idx)
            self._emit_debounced()
            return
        self._single_watch_indices = [i for i in self._single_watch_indices if i != cam_i]
        if self._single_focus_camera == cam_i:
            self._single_focus_camera = None
        self._rebuild_single_camera_buttons(record_cam)
        self._refresh_single_focus_preview()
        self._refresh_single_grid_layout()
        self._emit_debounced()

    def _effective_focus_camera(self, record_cam: int) -> int:
        if self._single_focus_camera is None:
            return int(record_cam)
        if self._single_focus_camera == int(record_cam):
            return int(record_cam)
        if self._single_focus_camera in self._single_watch_indices:
            return int(self._single_focus_camera)
        return int(record_cam)

    def _set_single_focus_camera(self, cam: int) -> None:
        record_cam = int(self._record[0].currentData() or 0)
        next_cam = int(cam)
        if next_cam != record_cam and next_cam not in self._single_watch_indices:
            return
        self._single_focus_camera = None if next_cam == record_cam else next_cam
        self._set_single_view_mode("focus")
        self._rebuild_single_camera_buttons(record_cam)
        self._refresh_single_focus_preview()
        self._emit_debounced()

    def _set_single_view_mode(self, mode: str) -> None:
        mode_norm = "grid" if str(mode) == "grid" else "focus"
        if self._single_view_mode == mode_norm:
            self._refresh_single_station_preview_mode_ui()
            return
        self._single_view_mode = mode_norm
        self._refresh_single_station_preview_mode_ui()
        self._emit_debounced()

    def _toggle_single_view_mode(self) -> None:
        self._set_single_view_mode("focus" if self._single_view_mode == "grid" else "grid")

    def _refresh_single_station_preview_mode_ui(self) -> None:
        active = self._station_column_count == 1 and not self._cinema_mode
        if self._single_toolbar_wrap is not None:
            self._single_toolbar_wrap.setVisible(active)
        if self._single_mode_toggle_btn is not None:
            self._single_mode_toggle_btn.setText(
                "Chế độ 1 cam" if self._single_view_mode == "grid" else "Chế độ lưới"
            )
        if self._single_preview_stack is not None:
            if not active:
                self._single_preview_stack.setCurrentIndex(0)
            else:
                self._single_preview_stack.setCurrentIndex(
                    1 if self._single_view_mode == "grid" else 0
                )
        self._refresh_single_focus_preview()
        self._refresh_single_grid_layout()

    def set_single_station_recording_active(self, active: bool) -> None:
        active = bool(active)
        if self._single_recording_active == active:
            return
        self._single_recording_active = active
        if self._station_column_count == 1:
            rec = int(self._record[0].currentData() or 0)
            self._rebuild_single_camera_buttons(rec)

    def _grid_columns_for_count(self, n: int) -> int:
        if n <= 2:
            return max(1, n)
        if n <= 4:
            return 2
        return 3

    def _refresh_single_grid_layout(self) -> None:
        lay = self._single_grid_layout
        wrap = self._single_grid_wrap
        if lay is None or wrap is None:
            return
        cams = self._single_watch_camera_set(int(self._record[0].currentData() or 0))
        while lay.count():
            it = lay.takeAt(0)
            w = it.widget()
            if w is not None:
                w.setParent(None)
        self._single_grid_labels = {}
        cols = self._grid_columns_for_count(len(cams))
        for i, cam in enumerate(cams):
            lb = QLabel(f"Cam {cam}")
            lb.setMinimumSize(220, 124)
            lb.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lb.setStyleSheet(
                "background:#2d2d2d;color:#c8c6c4;border:1px solid #484644;border-radius:8px;"
            )
            lb.setProperty("cam_index", cam)
            lb.mousePressEvent = (  # type: ignore[method-assign]
                lambda _ev, c=cam: self._set_single_focus_camera(c)
            )
            self._single_grid_labels[cam] = lb
            r = i // cols
            c = i % cols
            lay.addWidget(lb, r, c)
        for cam, frame in list(self._single_frames.items()):
            if cam in self._single_grid_labels:
                self._paint_single_grid_label(cam, frame)

    def _paint_single_grid_label(self, cam: int, frame: tuple[bytes, int, int]) -> None:
        lb = self._single_grid_labels.get(cam)
        if lb is None:
            return
        bgr, w, h = frame
        pix = bgr_bytes_to_pixmap(bgr, w, h, max_w=max(220, lb.width()))
        if pix is None:
            return
        lb.setPixmap(pix)
        lb.setScaledContents(False)

    def _refresh_single_focus_preview(self) -> None:
        if self._station_column_count != 1:
            return
        if self._single_view_mode != "focus":
            return
        if not self._preview:
            return
        rec = int(self._record[0].currentData() or 0)
        cam = self._effective_focus_camera(rec)
        frame = self._single_frames.get(cam)
        if frame is None:
            self.set_preview_column(0, cam, None, 0, 0)
            return
        bgr, w, h = frame
        self.set_preview_column(0, cam, bgr, w, h)

    def camera_indices_selected_in_ui(self) -> set[int]:
        return self._indices_from_combos()

    def _is_rtsp_column(self, col: int) -> bool:
        if not (0 <= col < len(self._record_kind)):
            return False
        return self._record_kind[col].checkedId() == 1

    def _rtsp_stream_active_in_ui(self, col: int) -> bool:
        """True khi radio RTSP + đã bấm «Kết nối» (hoặc đồng bộ từ config đã lưu RTSP)."""
        if not (0 <= col < len(self._rtsp_armed)):
            return False
        return (
            self._is_rtsp_column(col)
            and self._rtsp_armed[col]
            and bool(self._rtsp_url[col].text().strip())
        )

    def _apply_record_kind_visibility(self, col: int) -> None:
        if not (0 <= col < len(self._record)):
            return
        rtsp = self._is_rtsp_column(col)
        self._record[col].setVisible(not rtsp)
        self._rtsp_url[col].setVisible(rtsp)
        self._rtsp_connect_btn[col].setVisible(rtsp)

    def _rtsp_sticky_expanded(self, col: int) -> bool:
        """Đang dùng RTSP đã lưu / đã «Kết nối» — không thu gọn được (spec §4)."""
        if not (0 <= col < len(self._rtsp_armed)):
            return False
        return (
            self._is_rtsp_column(col)
            and bool(self._rtsp_url[col].text().strip())
            and self._rtsp_armed[col]
        )

    def _on_advanced_toggled(self, col: int, checked: bool) -> None:
        self._apply_advanced_visibility(col, checked)

    def _apply_advanced_visibility(self, col: int, expanded: bool) -> None:
        if not (0 <= col < len(self._record_kind)):
            return
        rb_rtsp = self._record_kind[col].button(1)
        if expanded:
            rb_rtsp.setVisible(True)
            self._apply_record_kind_visibility(col)
            self._refresh_preview_roi_lock(col)
            return
        rb_rtsp.setVisible(False)
        if self._is_rtsp_column(col):
            if self._rtsp_sticky_expanded(col):
                rb_rtsp.setVisible(True)
                if 0 <= col < len(self._adv_btn):
                    with QSignalBlocker(self._adv_btn[col]):
                        self._adv_btn[col].setChecked(True)
                self._apply_record_kind_visibility(col)
                self._refresh_preview_roi_lock(col)
                return
            bg = self._record_kind[col]
            with QSignalBlocker(bg):
                bg.button(0).setChecked(True)
            self._on_record_kind_changed(col)
        self._apply_record_kind_visibility(col)
        self._refresh_preview_roi_lock(col)

    def _on_record_kind_changed(self, col: int) -> None:
        if self._is_rtsp_column(col) and not self._rtsp_url[col].text().strip():
            with QSignalBlocker(self._rtsp_url[col]):
                self._rtsp_url[col].setText(RTSP_DEFAULT_URL_BY_COLUMN[col])
        self._rtsp_armed[col] = False
        self._apply_record_kind_visibility(col)
        if not self._is_rtsp_column(col):
            sel = int(self._record[col].currentData() or col)
            self._repopulate_record_combo(col, sel)
            self._emit_debounced()

    def _on_rtsp_text_changed(self, col: int) -> None:
        if not self._is_rtsp_column(col):
            return
        self._rtsp_armed[col] = False

    def _on_rtsp_connect_clicked(self, col: int) -> None:
        if not self._is_rtsp_column(col):
            return
        url = self._rtsp_url[col].text().strip()
        if not url:
            return
        self._rtsp_armed[col] = True
        self.rtsp_connect_requested.emit(col, url)

    def _other_column_usb_index(self, other: int) -> int | None:
        if self._rtsp_stream_active_in_ui(other):
            return None
        d = self._record[other].currentData()
        return int(d) if d is not None else None

    @staticmethod
    def _usb_index_for_sync(st: StationConfig, col: int) -> int:
        if st.record_camera_kind == "rtsp" and is_rtsp_stream_url(st.record_rtsp_url):
            return min(col, 9)
        ri = int(st.record_camera_index)
        if 0 <= ri <= 9:
            return ri
        return min(col, 9)

    def refresh_scanner_combos_sync(self) -> None:
        """Chỉ quét lại cổng COM (nhanh) — không chặn UI bằng probe camera."""
        for col in range(2):
            port = ""
            if self._scanner[col].count():
                d = self._scanner[col].currentData()
                port = str(d) if d else ""
            vid, pid = self._scanner_expected_vid_pid[col]
            self._repopulate_scanner_combo(
                self._scanner[col],
                port,
                expected_vid=vid,
                expected_pid=pid,
                col=col,
                probe_serial=True,
            )

    def set_refresh_busy(self, busy: bool) -> None:
        self._btn_refresh.setEnabled(not busy)
        self._btn_refresh.setText(
            "Đang quét camera…" if busy else "Làm mới camera & cổng COM"
        )

    def _on_refresh_clicked(self) -> None:
        self.refresh_scanner_combos_sync()
        self.refresh_devices_requested.emit()

    def apply_camera_probe_result(self, probed: list[int]) -> None:
        """Cập nhật danh sách camera sau probe nền (giống refresh_device_lists nhưng có sẵn probed)."""
        self._debounce.stop()
        self._cam_indices = sorted(set(probed or [0]) | self._indices_from_combos())
        pr0 = self._record[0].currentData()
        pr1 = self._record[1].currentData()
        sel0 = int(pr0) if pr0 is not None else self._cam_indices[0]
        sel1 = int(pr1) if pr1 is not None else self._cam_indices[min(1, len(self._cam_indices) - 1)]
        if sel0 not in self._cam_indices:
            sel0 = self._cam_indices[0]
        if sel1 not in self._cam_indices:
            sel1 = self._cam_indices[min(1, len(self._cam_indices) - 1)]
        if (
            self._station_column_count >= 2
            and not self._is_rtsp_column(0)
            and not self._is_rtsp_column(1)
        ):
            if sel0 == sel1:
                alt = next((i for i in self._cam_indices if i != sel0), None)
                if alt is None:
                    alt = (sel0 + 1) % 10
                sel1 = alt
        if not self._is_rtsp_column(0):
            self._repopulate_record_combo(0, sel0)
        if self._station_column_count >= 2 and not self._is_rtsp_column(1):
            self._repopulate_record_combo(1, sel1)

        for col in range(self._station_column_count):
            port = ""
            if self._scanner[col].count():
                d = self._scanner[col].currentData()
                port = str(d) if d else ""
            vid, pid = self._scanner_expected_vid_pid[col]
            self._repopulate_scanner_combo(
                self._scanner[col],
                port,
                expected_vid=vid,
                expected_pid=pid,
                col=col,
                probe_serial=True,
            )

            self._on_scanner_or_decode_changed(col, emit=False)

    def _emit_debounced(self) -> None:
        self._debounce.start()

    def _pick_root(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu video", self._root.text())
        if d:
            self._root.setText(d)
            self.fields_changed.emit()

    def sync_video_root(self, root_path: str) -> None:
        with QSignalBlocker(self._root):
            self._root.setText(root_path or "")

    def _repopulate_camera_combo(self, combo: QComboBox, indices: list[int], select: int) -> None:
        with QSignalBlocker(combo):
            combo.clear()
            for i in indices:
                combo.addItem(f"Camera {i}", i)
            idx = combo.findData(select)
            if idx < 0 and combo.count():
                idx = 0
            if idx >= 0:
                combo.setCurrentIndex(idx)

    def _repopulate_record_combo(self, col: int, select: int) -> None:
        """Mỗi cột chỉ chọn camera ghi khác cột kia (không hiện chung một webcam ở hai máy)."""
        if self._station_column_count < 2:
            allowed = list(self._cam_indices)
            if not allowed:
                allowed = list(range(10))
            if select not in allowed:
                select = allowed[0]
            self._repopulate_camera_combo(self._record[col], allowed, select)
            return
        other = 1 - col
        other_idx = self._other_column_usb_index(other)
        allowed = [i for i in self._cam_indices if other_idx is None or i != other_idx]
        if not allowed:
            allowed = [i for i in range(10) if other_idx is None or i != other_idx]
        if select not in allowed:
            select = allowed[0]
        self._repopulate_camera_combo(self._record[col], allowed, select)

    def _repopulate_scanner_combo(
        self,
        combo: QComboBox,
        select_port: str,
        *,
        expected_vid: str = "",
        expected_pid: str = "",
        col: int | None = None,
        probe_serial: bool = True,
    ) -> None:
        with QSignalBlocker(combo):
            combo.clear()
            combo.addItem("(Không — đọc mã bằng camera)", "")
            if not iter_raw_comports() and not (select_port or "").strip():
                combo.addItem(
                    "(Cài pyserial — pip install pyserial — chưa liệt kê COM)",
                    "",
                )
                combo.setCurrentIndex(0)
                if col is not None and 0 <= col < len(self._scanner_match_hint):
                    self._scanner_match_hint[col].setVisible(False)
                return
            sp = (select_port or "").strip()
            pairs = list_filtered_serial_ports(try_open_ports=probe_serial)
            listed = {d for d, _ in pairs}
            auto_port, auto_detected = choose_serial_port(
                selected_port=sp,
                expected_vid=expected_vid,
                expected_pid=expected_pid,
                try_open_ports=probe_serial,
            )
            if sp and sp not in listed:
                combo.addItem(f"{sp} — (đã lưu trong cấu hình)", sp)
            for device, label in pairs:
                combo.addItem(label, device)
            idx = combo.findData(auto_port)
            if idx < 0:
                idx = 0
            combo.setCurrentIndex(idx)
            if col is not None and 0 <= col < len(self._scanner_match_hint):
                hint = self._scanner_match_hint[col]
                if (
                    auto_detected
                    and auto_port
                    and len((expected_vid or "").strip()) == 4
                    and len((expected_pid or "").strip()) == 4
                ):
                    hint.setText(
                        f"Tự nhận diện theo VID:PID {expected_vid}:{expected_pid} -> {auto_port}"
                    )
                    hint.setVisible(True)
                elif (
                    len((expected_vid or "").strip()) == 4
                    and len((expected_pid or "").strip()) == 4
                    and not auto_port
                ):
                    hint.setText(
                        f"Không thấy thiết bị VID:PID {expected_vid}:{expected_pid} (đang dùng camera đọc mã)."
                    )
                    hint.setVisible(True)
                else:
                    hint.setVisible(False)

    def _indices_from_combos(self) -> set[int]:
        out: set[int] = set()
        for col in range(self._station_column_count):
            if self._rtsp_stream_active_in_ui(col):
                out.add(10 + col)
            else:
                d = self._record[col].currentData()
                if d is not None:
                    out.add(int(d))
        if self._station_column_count == 1:
            out |= set(self._single_watch_indices)
        return out

    def _on_add_single_preview_camera_clicked(self) -> None:
        if self._station_column_count != 1:
            return
        used = set(self._single_watch_indices)
        rec = int(self._record[0].currentData() or 0)
        used.add(rec)
        menu = QMenu(self)

        def _populate_menu_from(indices: list[int]) -> None:
            for cam in indices:
                c = int(cam)
                if c in used or c < 0 or c > 9:
                    continue
                act = menu.addAction(f"Camera {c}")
                act.setData(c)

        _populate_menu_from(self._cam_indices)
        if menu.isEmpty():
            # Fallback: probe lại ngay khi bấm "+ Thêm camera" để bắt kịp camera vừa cắm.
            fresh = probe_opencv_camera_indices(max_index=9, require_frame=False)
            merged = _normalize_usb_indices(
                sorted(set(self._cam_indices) | set(int(i) for i in fresh))
            )
            if merged:
                self._cam_indices = merged
                _populate_menu_from(self._cam_indices)
        if menu.isEmpty():
            QMessageBox.information(
                self,
                "Không còn camera để thêm",
                "Danh sách camera đã dùng hết hoặc chưa có camera USB mới.",
            )
            return
        picked = menu.exec(self.mapToGlobal(self.rect().center()))
        if picked is None:
            return
        data = picked.data()
        if data is None:
            return
        try:
            cam = int(data)
        except (TypeError, ValueError):
            return
        if cam in used:
            return
        self._single_watch_indices.append(cam)
        self._single_watch_indices = _normalize_usb_indices(self._single_watch_indices)
        self._rebuild_single_camera_buttons(rec)
        self._refresh_single_grid_layout()
        self._emit_debounced()

    def _on_station_name_finished(self) -> None:
        self._emit_debounced()

    def refresh_device_lists(self) -> None:
        """Probe đồng bộ — chỉ dùng khi không có UI thread (test); UI dùng probe nền + apply_camera_probe_result."""
        probed = probe_opencv_camera_indices(max_index=6, require_frame=False)
        self.apply_camera_probe_result(probed)

    def _on_record_changed(self, col: int) -> None:
        if self._is_rtsp_column(col):
            return
        if self._is_rtsp_column(0) or self._is_rtsp_column(1):
            self._repopulate_record_combo(
                col, int(self._record[col].currentData() or col)
            )
            self._emit_debounced()
            return
        if self._station_column_count < 2:
            self._repopulate_record_combo(
                col, int(self._record[col].currentData() or col)
            )
            rec = int(self._record[col].currentData() or col)
            self._single_watch_indices = [i for i in self._single_watch_indices if i != rec]
            self._rebuild_single_camera_buttons(rec)
            self._refresh_single_grid_layout()
            self._emit_debounced()
            return
        r0 = int(self._record[0].currentData() or 0)
        r1 = int(self._record[1].currentData() or 0)
        if r0 == r1:
            alt = next((i for i in self._cam_indices if i != r0), None)
            if alt is None:
                alt = (r0 + 1) % 10
            o = 1 - col
            if o == 0:
                r0 = alt
            else:
                r1 = alt
        self._repopulate_record_combo(0, r0)
        self._repopulate_record_combo(1, r1)
        self._emit_debounced()

    def _scanner_kind_data(self, col: int) -> str:
        if not (0 <= col < len(self._scanner_input_kind)):
            return "com"
        d = self._scanner_input_kind[col].currentData()
        return str(d or "com")

    def _on_scanner_input_kind_changed(self, col: int, emit: bool = True) -> None:
        if not (0 <= col < len(self._scanner_input_kind)):
            return
        kind = self._scanner_kind_data(col)
        is_com = kind == "com"
        self._scanner[col].setVisible(is_com)
        self._hid_row_widget[col].setVisible(False)
        if 0 <= col < len(self._hid_block_widget):
            self._hid_block_widget[col].setVisible(True)
        if not is_com:
            self._repopulate_hid_device_combo(col)
        if 0 <= col < len(self._scanner_match_hint) and not is_com:
            self._scanner_match_hint[col].setVisible(False)
        if 0 <= col < len(self._tl_scan):
            self._tl_scan[col].setText(
                "Máy quét (USB–COM)" if is_com else "Máy quét HID POS"
            )
        if 0 <= col < len(self._decode_hint):
            dh = self._decode_hint[col]
            if is_com:
                dh.setText(
                    "Khi chọn cổng COM ở trên, mã vạch đọc từ máy quét USB–serial.\n"
                    "Để trống COM thì dùng camera đọc mã (pyzbar) bên dưới."
                )
            else:
                dh.setText(
                    "HID POS — raw: app đọc mã qua hidapi (VID/PID); khi cửa sổ ẩn vẫn nhận nếu máy ở chế độ POS/raw. "
                    "Ẩn cửa sổ / chỉ icon khay: Cài đặt → «Thu vào khay hệ thống» (không phải do chọn VID/PID). "
                    "Thiếu hidapi: pip install -e ."
                )
        if emit:
            self._emit_debounced()
        self._apply_manual_order_readonly()
        self._refresh_scanner_selected_label(col)
        self._refresh_preview_roi_lock(col)

    def _on_hid_vid_pid_changed(self, col: int) -> None:
        if self._scanner_kind_data(col) != "hid_pos":
            return
        v = self._hid_vid[col].text().strip().upper()
        p = self._hid_pid[col].text().strip().upper()
        if len(v) != 4 or len(p) != 4:
            return
        for oc in range(2):
            if oc == col:
                continue
            if self._scanner_kind_data(oc) != "hid_pos":
                continue
            ov = self._hid_vid[oc].text().strip().upper()
            op = self._hid_pid[oc].text().strip().upper()
            if ov == v and op == p:
                with QSignalBlocker(self._hid_vid[oc]):
                    self._hid_vid[oc].clear()
                with QSignalBlocker(self._hid_pid[oc]):
                    self._hid_pid[oc].clear()

    @staticmethod
    def _hid_combo_key(v: int, p: int) -> str:
        return f"{v:04X}:{p:04X}"

    def _repopulate_hid_device_combo(self, col: int) -> None:
        if not (0 <= col < len(self._hid_device_combo)):
            return
        combo = self._hid_device_combo[col]
        usage_lbl = self._hid_usage_label[col]
        raw, err = enumerate_hid_or_error()
        with QSignalBlocker(combo):
            combo.clear()
            combo.addItem("(Chọn thủ công / nhập bên dưới)", None)
            if err:
                usage_lbl.setText(f"Không liệt kê HID: {err}")
                usage_lbl.setVisible(True)
                combo.setCurrentIndex(0)
                return
            assert raw is not None
            pos_n = len(list_usage_page_devices(raw, HID_POS_USAGE_PAGE))
            if pos_n == 0:
                usage_lbl.setText(
                    "Không thấy thiết bị Usage Page 0x8C (HID POS). Vẫn có thể chọn theo tên trong danh sách."
                )
            elif pos_n == 1:
                usage_lbl.setText(
                    "Gợi ý: 1 thiết bị HID POS (0x8C) — chọn trong danh sách nếu đúng máy quét."
                )
            else:
                usage_lbl.setText(
                    f"Gợi ý: {pos_n} thiết bị HID POS (0x8C) — chọn đúng dòng hoặc dùng «Thiết lập máy quét»."
                )
            usage_lbl.setVisible(True)
            for d in filter_scanner_candidates(raw):
                v, p = vid_pid_int_from_device(d)
                combo.addItem(device_label(d), self._hid_combo_key(v, p))
        vtxt = self._hid_vid[col].text().strip().upper()
        ptxt = self._hid_pid[col].text().strip().upper()
        if len(vtxt) == 4 and len(ptxt) == 4:
            try:
                v = int(vtxt, 16)
                p = int(ptxt, 16)
            except ValueError:
                combo.setCurrentIndex(0)
                return
            idx = combo.findData(self._hid_combo_key(v, p))
            combo.setCurrentIndex(idx if idx >= 0 else 0)
            if idx >= 0:
                usage_lbl.setText(
                    f"Đã nhận diện máy quét HID POS: {vtxt}:{ptxt}."
                )
                usage_lbl.setVisible(True)
        else:
            combo.setCurrentIndex(0)

    def _on_hid_device_combo_changed(self, col: int) -> None:
        if self._scanner_kind_data(col) != "hid_pos":
            return
        if not (0 <= col < len(self._hid_device_combo)):
            return
        key = self._hid_device_combo[col].currentData()
        if key is None or not isinstance(key, str):
            return
        parts = key.split(":", 1)
        if len(parts) != 2:
            return
        try:
            v = int(parts[0], 16)
            p = int(parts[1], 16)
        except ValueError:
            return
        with QSignalBlocker(self._hid_vid[col]):
            self._hid_vid[col].setText(f"{v:04X}")
        with QSignalBlocker(self._hid_pid[col]):
            self._hid_pid[col].setText(f"{p:04X}")
        self._on_hid_vid_pid_changed(col)
        self._emit_debounced()
        self._refresh_scanner_selected_label(col)

    def _on_hid_refresh_clicked(self, col: int) -> None:
        if self._scanner_kind_data(col) != "hid_pos":
            return
        raw, err = enumerate_hid_or_error()
        if err:
            QMessageBox.warning(self, "HID", err)
            return
        self._repopulate_hid_device_combo(col)

    def _open_hid_wizard(self, col: int) -> None:
        if self._scanner_kind_data(col) != "hid_pos":
            return
        QMessageBox.information(
            self,
            "Tự phát hiện máy quét",
            "Bước 1: Bấm icon răng cưa để mở cài đặt máy quét và quét mã chuyển chế độ Chạy ngầm.\n"
            "Bước 2: Bấm «Tự phát hiện máy quét» để dò thiết bị.\n"
            "Bước 3: Nếu cần, rút/cắm lại máy quét và hoàn tất wizard.",
        )
        w = HidPosSetupWizard(self)

        def _apply(v: int, p: int) -> None:
            with QSignalBlocker(self._hid_vid[col]):
                self._hid_vid[col].setText(f"{v:04X}")
            with QSignalBlocker(self._hid_pid[col]):
                self._hid_pid[col].setText(f"{p:04X}")
            self._on_hid_vid_pid_changed(col)
            self._repopulate_hid_device_combo(col)
            self._emit_debounced()

        w.vid_pid_chosen.connect(_apply)
        w.exec()
        self._refresh_scanner_selected_label(col)

    def _open_scanner_mode_dialog(self, col: int) -> None:
        del col
        dlg = ScannerModeDialog(self)
        dlg.exec()

    def _col_dedicated_scanner_active(self, col: int) -> bool:
        if not (0 <= col < len(self._scanner_input_kind)):
            return False
        if self._scanner_kind_data(col) == "hid_pos":
            v = self._hid_vid[col].text().strip()
            p = self._hid_pid[col].text().strip()
            return len(v) == 4 and len(p) == 4
        port = self._scanner[col].currentData()
        return bool(port and str(port).strip())

    def _manual_order_readonly_for_col(self, col: int) -> bool:
        """Chỉ khóa ô Mã đơn khi dùng COM có cổng (serial worker tự điền)."""
        if not (0 <= col < len(self._scanner_input_kind)):
            return False
        kind = self._scanner_kind_data(col)
        if kind in ("hid_pos", "keyboard"):
            return False
        if kind == "com":
            port = self._scanner[col].currentData()
            return bool(port and str(port).strip())
        return False

    def _preview_roi_unlocked_for_column(self, col: int) -> bool:
        """True = cho phép kéo ROI (đọc mã bằng camera khi không có COM/HID)."""
        if not (0 <= col < len(self._scanner_input_kind)):
            return True
        if self._scanner_kind_data(col) == "hid_pos":
            return False
        port = str(self._scanner[col].currentData() or "").strip()
        return not bool(port)

    def _refresh_preview_roi_lock(self, col: int) -> None:
        if not (0 <= col < len(self._preview)):
            return
        self._preview[col].set_roi_locked(
            not self._preview_roi_unlocked_for_column(col)
        )

    def _on_scanner_or_decode_changed(self, col: int, emit: bool = True) -> None:
        port = self._scanner[col].currentData()
        use_serial = bool(port and str(port).strip())
        if emit:
            self._emit_debounced()

        if use_serial:
            p = str(port).strip()
            for oc in range(2):
                if oc == col:
                    continue
                od = self._scanner[oc].currentData()
                if od is not None and str(od).strip() == p:
                    with QSignalBlocker(self._scanner[oc]):
                        self._scanner[oc].setCurrentIndex(0)
                    self._on_scanner_or_decode_changed(oc, emit=False)
        self._apply_manual_order_readonly()
        self._refresh_scanner_selected_label(col)
        self._refresh_preview_roi_lock(col)

    def _refresh_scanner_selected_label(self, col: int) -> None:
        if not (0 <= col < len(self._scanner_selected_label)):
            return
        lbl = self._scanner_selected_label[col]
        if 0 <= col < len(self._scanner_match_hint) and self._scanner_kind_data(col) == "hid_pos":
            self._scanner_match_hint[col].setVisible(False)
        if self._scanner_kind_data(col) == "com":
            txt = self._scanner[col].currentText().strip()
            lbl.setText(f"Máy quét đã chọn: {txt or 'chưa có'}")
            return
        txt = self._hid_device_combo[col].currentText().strip()
        if not txt or txt.startswith("(Chọn"):
            v = self._hid_vid[col].text().strip().upper()
            p = self._hid_pid[col].text().strip().upper()
            if len(v) == 4 and len(p) == 4:
                txt = f"HID POS {v}:{p}"
        lbl.setText(f"Máy quét đã chọn: {txt or 'chưa có'}")

    def _apply_manual_order_readonly(self) -> None:
        """Ô «Mã đơn» chỉ khóa khi COM có cổng."""
        try:
            for col in range(2):
                self._manual_col_order[col].setReadOnly(
                    self._manual_order_readonly_for_col(col)
                )
        except Exception:
            log_session_error(
                "Lỗi trong _apply_manual_order_readonly.",
                exc_info=sys.exc_info(),
            )

    def set_manual_order_text(self, col: int, text: str, *, focus: bool = True) -> None:
        """Ghi mã vào đúng cột (luồng serial); focus hoãn 1 tick để tránh tái nhập/Qt khi tín hiệu từ thread."""
        try:
            if not (0 <= col < len(self._manual_col_order)):
                return
            mo = self._manual_col_order[col]
            with QSignalBlocker(mo):
                mo.setText(text)
            if focus:

                def _defer_focus() -> None:
                    try:
                        if not (0 <= col < len(self._manual_col_order)):
                            return
                        w = self._manual_col_order[col]
                        if not w.isVisible():
                            return
                        win = w.window()
                        if win is None or not win.isVisible():
                            return
                        w.setFocus(Qt.FocusReason.OtherFocusReason)
                    except Exception:
                        log_session_error(
                            "Lỗi defer focus ô Mã đơn (serial).",
                            exc_info=sys.exc_info(),
                        )

                QTimer.singleShot(0, _defer_focus)
        except Exception:
            log_session_error(
                "Lỗi set_manual_order_text (serial / ô Mã đơn).",
                exc_info=sys.exc_info(),
            )

    def sync_from_config(
        self,
        cfg: AppConfig,
        *,
        probed_override: list[int] | None = None,
        fast_serial_scan: bool = False,
    ) -> None:
        # Hủy debounce đang chờ — nếu không, ~320ms sau sync khởi động vẫn bắn fields_changed
        # → MainWindow._on_dual_fields_changed → _restart_scan_workers lần 2 ngay lúc worker
        # đang probe (log: chỉ thấy probe_done cam 0, cam 1 chưa kịp → xung đột MSMF / crash).
        self._debounce.stop()
        self.set_station_column_count(max(1, min(2, len(cfg.stations))))
        with QSignalBlocker(self._root):
            self._root.setText(cfg.video_root)
        self._scanner_com_only = bool(cfg.scanner_com_only)
        if probed_override is not None:
            probed = list(probed_override)
        else:
            probed = probe_opencv_camera_indices(max_index=6, require_frame=False)
        self._cam_indices = _merge_probe_with_config(probed, cfg)
        r0 = (
            self._usb_index_for_sync(cfg.stations[0], 0)
            if len(cfg.stations) > 0
            else 0
        )
        r1 = (
            self._usb_index_for_sync(cfg.stations[1], 1)
            if len(cfg.stations) > 1
            else 1
        )
        if r0 not in self._cam_indices:
            r0 = self._cam_indices[0]
        if r1 not in self._cam_indices:
            r1 = self._cam_indices[min(1, len(self._cam_indices) - 1)]
        if r0 == r1:
            alt = next((i for i in self._cam_indices if i != r0), None)
            if alt is None:
                alt = (r0 + 1) % 10
            r1 = alt
        self._repopulate_record_combo(0, r0)
        self._repopulate_record_combo(1, r1)

        for col in range(2):
            if col >= len(cfg.stations):
                continue
            s = cfg.stations[col]
            is_rtsp = s.record_camera_kind == "rtsp" and is_rtsp_stream_url(
                s.record_rtsp_url
            )
            bg = self._record_kind[col]
            with QSignalBlocker(bg):
                if is_rtsp:
                    bg.button(1).setChecked(True)
                else:
                    bg.button(0).setChecked(True)
            with QSignalBlocker(self._rtsp_url[col]):
                self._rtsp_url[col].setText((s.record_rtsp_url or "").strip())
            self._apply_record_kind_visibility(col)
            vid = (s.scanner_usb_vid or "").strip().upper()
            pid = (s.scanner_usb_pid or "").strip().upper()
            self._scanner_expected_vid_pid[col] = (vid, pid)
            self._repopulate_scanner_combo(
                self._scanner[col],
                (s.scanner_serial_port or "").strip(),
                expected_vid=vid,
                expected_pid=pid,
                col=col,
                probe_serial=not fast_serial_scan,
            )
            skind = getattr(s, "scanner_input_kind", "com")
            with QSignalBlocker(self._scanner_input_kind[col]):
                sk_idx = self._scanner_input_kind[col].findData(skind)
                if sk_idx >= 0:
                    self._scanner_input_kind[col].setCurrentIndex(sk_idx)
            with QSignalBlocker(self._hid_vid[col]):
                self._hid_vid[col].setText((s.scanner_usb_vid or "").strip())
            with QSignalBlocker(self._hid_pid[col]):
                self._hid_pid[col].setText((s.scanner_usb_pid or "").strip())
            self._on_scanner_input_kind_changed(col, emit=False)
            with QSignalBlocker(self._name[col]):
                self._name[col].setText(s.packer_label)
            self._on_scanner_or_decode_changed(col, emit=False)
            self._refresh_scanner_selected_label(col)
            with QSignalBlocker(self._preview[col]):
                self._preview[col].set_roi_norm(s.record_roi_norm)
            self._rtsp_armed[col] = bool(is_rtsp)

        for col in range(2):
            if col >= len(cfg.stations):
                continue
            if not self._is_rtsp_column(col):
                self._repopulate_record_combo(
                    col,
                    int(
                        self._record[col].currentData()
                        or self._usb_index_for_sync(cfg.stations[col], col)
                    ),
                )
            self._apply_manual_order_readonly()
        if cfg.stations:
            s0 = cfg.stations[0]
            rec0 = int(self._record[0].currentData() or self._usb_index_for_sync(s0, 0))
            self._single_watch_indices = _normalize_usb_indices(
                list(getattr(s0, "extra_preview_usb_indices", []))
            )
            self._single_watch_indices = [i for i in self._single_watch_indices if i != rec0]
            mode_raw = str(getattr(s0, "single_station_view_mode", "focus")).strip().lower()
            self._single_view_mode = "grid" if mode_raw == "grid" else "focus"
            focus_raw = getattr(s0, "focused_preview_usb_index", None)
            try:
                focus_int = int(focus_raw) if focus_raw is not None else None
            except (TypeError, ValueError):
                focus_int = None
            if focus_int is not None and focus_int not in self._single_watch_indices and focus_int != rec0:
                focus_int = None
            self._single_focus_camera = focus_int
            self._rebuild_single_camera_buttons(rec0)
            self._refresh_single_grid_layout()
        self._refresh_layout_mode()
        for col in range(min(2, len(cfg.stations))):
            s = cfg.stations[col]
            is_rtsp_cfg = s.record_camera_kind == "rtsp" and is_rtsp_stream_url(
                s.record_rtsp_url
            )
            need_adv = bool(
                is_rtsp_cfg or self._preview_roi_unlocked_for_column(col)
            )
            if 0 <= col < len(self._adv_btn):
                with QSignalBlocker(self._adv_btn[col]):
                    self._adv_btn[col].setChecked(need_adv)
            self._apply_advanced_visibility(col, need_adv)

    def duplicate_scanner_ports(self) -> bool:
        if self._station_column_count < 2:
            return False
        def key(col: int) -> tuple[str, str] | None:
            if not (0 <= col < len(self._scanner_input_kind)):
                return None
            if self._scanner_kind_data(col) == "hid_pos":
                v = self._hid_vid[col].text().strip().upper()
                p = self._hid_pid[col].text().strip().upper()
                if len(v) == 4 and len(p) == 4:
                    return ("hid", f"{v}:{p}")
                return None
            raw = str(self._scanner[col].currentData() or "").strip()
            if raw:
                return ("com", raw)
            return None

        k0, k1 = key(0), key(1)
        return k0 is not None and k0 == k1

    def apply_to_config(self, cfg: AppConfig) -> None:
        cfg.video_root = self._root.text().strip()
        vid_pid_map = vid_pid_by_device()
        for col in range(min(2, len(cfg.stations))):
            s = cfg.stations[col]
            skind = str(self._scanner_input_kind[col].currentData() or "com")
            raw_port = self._scanner[col].currentData()
            port = ""
            if raw_port and str(raw_port).strip():
                port = str(raw_port).strip()
            if skind == "hid_pos":
                port = ""
                cfg_vid = (self._hid_vid[col].text() or "").strip().upper()
                cfg_pid = (self._hid_pid[col].text() or "").strip().upper()
            else:
                cfg_vid = (s.scanner_usb_vid or "").strip().upper()
                cfg_pid = (s.scanner_usb_pid or "").strip().upper()
                if port and (not cfg_vid or not cfg_pid):
                    detected = vid_pid_map.get(port, ("", ""))
                    dvid, dpid = detected
                    if dvid and dpid:
                        cfg_vid, cfg_pid = dvid, dpid
            kind = "rtsp" if self._record_kind[col].checkedId() == 1 else "usb"
            url = self._rtsp_url[col].text().strip()
            if kind == "rtsp" and (not url or not self._rtsp_armed[col]):
                kind = "usb"
            if kind == "usb":
                rd = self._record[col].currentData()
                rec = int(rd) if rd is not None else 0
            else:
                rec = 10 + col
            cfg.stations[col] = replace(
                s,
                packer_label=(self._name[col].text().strip() or f"Máy {col + 1}"),
                record_camera_kind=kind,
                record_rtsp_url=url if kind == "rtsp" else "",
                record_camera_index=rec,
                decode_camera_index=rec,
                scanner_serial_port=port,
                scanner_serial_baud=int(s.scanner_serial_baud),
                scanner_usb_vid=cfg_vid,
                scanner_usb_pid=cfg_pid,
                scanner_input_kind="hid_pos" if skind == "hid_pos" else "com",
                preview_display_index=-1,
                extra_preview_usb_indices=(
                    list(self._single_watch_indices) if col == 0 else []
                ),
                single_station_view_mode=(
                    self._single_view_mode if col == 0 else "focus"
                ),
                focused_preview_usb_index=(
                    self._single_focus_camera if col == 0 else None
                ),
                record_roi_norm=self._preview[col].get_roi_norm(),
            )

    def set_cinema_mode(self, on: bool) -> None:
        """Phóng to cửa sổ: ẩn form, chỉ hai khung camera giãn full."""
        if self._cinema_mode == on:
            return
        self._cinema_mode = on
        self._refresh_layout_mode()

    def preview_max_scale_px(self, col: int) -> int:
        """Cạnh dài tối đa khi scale pixmap (theo DPR), để preview sắc khi cửa sổ lớn."""
        if not (0 <= col < len(self._preview)):
            return 520
        lab = self._preview[col]
        dpr = float(lab.devicePixelRatioF())
        w = int(lab.width() * dpr)
        h = int(lab.height() * dpr)
        floor = 480 if self._cinema_mode else 360
        m = max(w, h, floor)
        if m < 400:
            m = 520
        cap = 2560 if self._cinema_mode else 720
        return min(m, cap)

    def preview_uses_fast_scale(self) -> bool:
        """Chế độ thường: Fast cho nhẹ; cinema: Smooth vì khung lớn."""
        return not self._cinema_mode

    def set_preview_roi_locked(self, col: int, locked: bool) -> None:
        if 0 <= col < len(self._preview):
            self._preview[col].set_roi_locked(locked)

    def focus_default_order_input(self) -> None:
        """Đưa tiêu điểm vào ô mã đơn quầy 1."""
        if self._manual_col_order:
            self._manual_col_order[0].setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def preview_cameras_for_column(self, col: int, default_cam: int) -> set[int]:
        if col != 0 or self._station_column_count != 1:
            return {int(default_cam)}
        cams = set(self._single_watch_camera_set(int(default_cam)))
        if self._single_view_mode == "focus":
            return {self._effective_focus_camera(int(default_cam))}
        return cams

    def clear_previews(self) -> None:
        self._single_frames.clear()
        for i in range(len(self._preview)):
            self._preview[i].clear_frame()
        for lb in self._single_grid_labels.values():
            lb.clear()

    def set_column_recording_banner(self, col: int, text: str | None) -> None:
        """Banner chữ (fallback). Ẩn: None — xóa cả pixmap."""
        if not (0 <= col < len(self._record_banner)):
            return
        lab = self._record_banner[col]
        if text:
            lab.clear()
            lab.setStyleSheet(self._BANNER_TEXT_STYLE)
            lab.setText(text)
            lab.setVisible(True)
        else:
            lab.clear()
            lab.setStyleSheet(self._BANNER_TEXT_STYLE)
            lab.setVisible(False)

    def set_column_order_pending(self, col: int, order: str | None) -> None:
        """Badge đỏ «Đang quét đơn» trước khi encoder bắt đầu ghi; None = ẩn."""
        if not (0 <= col < len(self._record_banner)):
            return
        lab = self._record_banner[col]
        lab.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
            | Qt.TextInteractionFlag.TextSelectableByKeyboard
        )
        if order:
            short = order if len(order) <= 48 else order[:45] + "…"
            lab.clear()
            lab.setStyleSheet(self._PENDING_ORDER_BANNER_STYLE)
            lab.setText(f"Đang quét đơn: {short}")
            lab.setScaledContents(False)
            lab.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            lab.setVisible(True)
        else:
            lab.clear()
            lab.setStyleSheet(self._BANNER_TEXT_STYLE)
            lab.setVisible(False)

    def set_column_recording_overlay_pixmap(self, col: int, pix: Optional[QPixmap]) -> None:
        """Chip giống burn-in video (nền bo tròn + chữ), trong suốt ngoài vùng chip."""
        if not (0 <= col < len(self._record_banner)):
            return
        lab = self._record_banner[col]
        lab.clear()
        if pix is not None and not pix.isNull():
            lab.setStyleSheet("background: transparent; border: none; padding: 0;")
            lab.setPixmap(pix)
            lab.setScaledContents(False)
            lab.setAlignment(
                Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            lab.setVisible(True)
        else:
            lab.setStyleSheet(self._BANNER_TEXT_STYLE)
            lab.setVisible(False)

    def clear_recording_banners(self) -> None:
        for i in range(len(self._record_banner)):
            self.set_column_recording_banner(i, None)

    def set_column_recording_timer(self, col: int, text: str | None) -> None:
        """Đồng hồ đếm thời gian ghi (màu đỏ), §3.2 — hiện khi đang quay."""
        if not (0 <= col < len(self._record_elapsed)):
            return
        lab = self._record_elapsed[col]
        if text:
            if lab.text() == text and lab.isVisible():
                return
            lab.setText(text)
            lab.setVisible(True)
        else:
            if not lab.isVisible() and not lab.text():
                return
            lab.clear()
            lab.setVisible(False)

    def clear_recording_timers(self) -> None:
        for i in range(len(self._record_elapsed)):
            self.set_column_recording_timer(i, None)

    def has_decode_camera_collision(self) -> bool:
        """Hai quầy cùng camera đọc mã (camera = mã nguồn) khi không dùng COM/HID."""
        if self._station_column_count < 2:
            return False
        indices: list[int] = []
        for col in range(2):
            if self._col_dedicated_scanner_active(col):
                continue
            if self._rtsp_stream_active_in_ui(col):
                indices.append(10 + col)
            else:
                rd = self._record[col].currentData()
                if rd is not None:
                    indices.append(int(rd))
        return len(indices) == 2 and indices[0] == indices[1]

    def has_decode_on_peer_record_collision(self) -> bool:
        """Mã nguồn = camera ghi quầy này; luôn khác camera ghi quầy kia nên không còn xung đột kiểu cũ."""
        return False

    def clear_manual_order_column(self, col: int) -> None:
        """Xóa ô mã sau khi đã gửi (đúng quy trình máy quét: mỗi lần quét = một chuỗi mới)."""
        try:
            if not (0 <= col < len(self._manual_col_order)):
                return
            mo = self._manual_col_order[col]
            with QSignalBlocker(mo):
                mo.clear()
        except Exception:
            log_session_error(
                "Lỗi clear_manual_order_column.",
                exc_info=sys.exc_info(),
            )

    def _emit_manual_col(self, col: int, *, source: str = "button") -> None:
        if not (0 <= col < len(self._manual_col_order)):
            return
        if source == "enter" and self._scanner_com_only:
            kind = self._scanner_kind_data(col)
            if kind not in ("hid_pos", "keyboard"):
                return
        text = normalize_manual_order_text(self._manual_col_order[col].text())
        if not text:
            return
        self.manual_order_submitted.emit(col, text)

    def set_preview_column(
        self,
        col: int,
        cam_idx: int,
        bgr: bytes | None,
        src_w: int,
        src_h: int,
    ) -> None:
        if not (0 <= col < len(self._preview)):
            return
        if self._station_column_count == 1 and col == 0:
            if bgr is None or src_w <= 0 or src_h <= 0:
                self._single_frames.pop(int(cam_idx), None)
            else:
                self._single_frames[int(cam_idx)] = (bytes(bgr), int(src_w), int(src_h))
                if int(cam_idx) in self._single_grid_labels:
                    self._paint_single_grid_label(int(cam_idx), self._single_frames[int(cam_idx)])
            if self._single_view_mode == "grid":
                return
            if int(cam_idx) != self._effective_focus_camera(int(self._record[0].currentData() or 0)):
                return
        lab = self._preview[col]
        if bgr is None or src_w <= 0 or src_h <= 0:
            lab.clear_frame()
        else:
            lab.set_full_frame_bgr(bgr, src_w, src_h)
