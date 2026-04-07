from __future__ import annotations

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
    QPushButton,
    QRadioButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from packrecorder.camera_probe import probe_opencv_camera_indices
from packrecorder.config import AppConfig, StationConfig
from packrecorder.order_input import normalize_manual_order_text
from packrecorder.serial_ports import iter_raw_comports, list_filtered_serial_ports
from packrecorder.ui.roi_preview_label import RoiPreviewLabel

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
        if s.record_camera_kind == "rtsp" and (s.record_rtsp_url or "").strip():
            continue
        out.add(int(s.record_camera_index))
        out.add(int(s.decode_camera_index))
    return out


def _merge_probe_with_config(probed: list[int], cfg: AppConfig) -> list[int]:
    base = set(probed) if probed else {0}
    base |= _station_camera_indices(list(cfg.stations))
    return sorted(base)


class DualStationWidget(QWidget):
    """Hai cột: camera ghi, máy quét COM (USB serial), hoặc camera đọc mã."""

    _BANNER_TEXT_STYLE = (
        "background-color:#ffebee;color:#b71c1c;padding:4px 8px;"
        "font-size:12px;font-weight:bold;border-radius:4px;border:1px solid #c62828;"
        "font-family:Consolas,'Cascadia Mono','Segoe UI',sans-serif;"
    )

    fields_changed = Signal()
    refresh_devices_requested = Signal()
    manual_order_submitted = Signal(int, str)
    rtsp_connect_requested = Signal(int, str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._cinema_mode = False
        self._cam_indices: list[int] = [0, 1]
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(320)
        self._debounce.timeout.connect(self.fields_changed.emit)

        self._root = QLineEdit()
        self._root.setPlaceholderText("Thư mục lưu video…")
        self._root.editingFinished.connect(self._emit_debounced)
        btn_browse = QPushButton("Chọn thư mục…")
        btn_browse.clicked.connect(self._pick_root)

        btn_refresh = QPushButton("Làm mới camera & cổng COM")
        btn_refresh.setToolTip(
            "Quét lại webcam đang cắm và cổng USB serial (máy quét thường hiện là COMx)."
        )
        self._btn_refresh = btn_refresh
        btn_refresh.clicked.connect(self._on_refresh_clicked)

        row_paths = QHBoxLayout()
        row_paths.setContentsMargins(0, 0, 0, 0)
        row_paths.addWidget(QLabel("Lưu file vào:"))
        row_paths.addWidget(self._root, 1)
        row_paths.addWidget(btn_browse)
        row_paths.addWidget(btn_refresh)

        self._top_bar = QWidget()
        top = QVBoxLayout(self._top_bar)
        top.setContentsMargins(0, 0, 0, 0)
        top.setSpacing(6)
        top.addLayout(row_paths)

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
        self._decode_hint: list[QLabel] = []
        self._name: list[QLineEdit] = []
        self._manual_col_order: list[QLineEdit] = []

        columns = QHBoxLayout()
        for col in range(2):
            box = QGroupBox(f"Máy {col + 1}")
            self._group_boxes.append(box)
            v = QVBoxLayout(box)
            banner = QLabel()
            banner.setVisible(False)
            banner.setWordWrap(False)
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
                "background-color:#ffebee;color:#b71c1c;padding:4px 6px;"
                "font-size:12px;font-weight:bold;border-radius:4px;"
                "font-family:Consolas,'Cascadia Mono','Segoe UI Mono',monospace;"
                "border:1px solid #c62828;"
            )
            self._record_elapsed.append(elapsed)
            v.addWidget(elapsed, 0)

            row_m = QHBoxLayout()
            row_m.setContentsMargins(0, 4, 0, 0)
            mo = QLineEdit()
            mo.setPlaceholderText(
                f"Máy {col + 1}: nhập mã (+ Enter hoặc nút) — mỗi lần luôn gửi đúng chữ trong ô. "
                "COM: quét lặp cùng mã → dừng. Camera: đổi mã mới mới dừng/chuyển đơn."
            )
            mo.setMinimumHeight(28)
            mo.returnPressed.connect(lambda c=col: self._emit_manual_col(c))
            btn_m = QPushButton("Bắt đầu ghi")
            btn_m.setToolTip(
                "Gửi mã đơn cho quầy này — cùng luồng với máy quét / camera đọc mã."
            )
            btn_m.clicked.connect(lambda _checked=False, c=col: self._emit_manual_col(c))
            row_m.addWidget(QLabel("Mã đơn:"))
            row_m.addWidget(mo, 1)
            row_m.addWidget(btn_m)
            order_row_w = QWidget()
            order_row_w.setLayout(row_m)
            self._manual_col_order.append(mo)
            v.addWidget(order_row_w, 0)

            prev = RoiPreviewLabel()
            prev.setMinimumSize(360, 200)
            prev.setMaximumHeight(280)
            prev.roi_changed.connect(self._emit_debounced)
            self._preview.append(prev)
            v.addWidget(prev, 1)

            form_w = QWidget()
            form_l = QVBoxLayout(form_w)
            form_l.setContentsMargins(0, 0, 0, 0)
            self._column_forms.append(form_w)

            g = QGridLayout()
            src_lab = QLabel("Camera ghi (mã nguồn)")
            src_lab.setToolTip(
                "USB: webcam chỉ số. RTSP: URL đầy đời (có thể sửa trong file config.json). "
                "Một nguồn cho xem trước, ghi và đọc mã (pyzbar) khi không dùng COM."
            )
            g.addWidget(src_lab, 0, 0)
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
            g.addWidget(kind_w, 0, 1)
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
            btn_rtsp.setVisible(False)
            btn_rtsp.clicked.connect(
                lambda _checked=False, c=col: self._on_rtsp_connect_clicked(c)
            )
            cam_stack.addWidget(btn_rtsp)
            self._rtsp_connect_btn.append(btn_rtsp)
            cw = QWidget()
            cw.setLayout(cam_stack)
            g.addWidget(cw, 1, 0, 1, 2)
            self._record.append(rc)
            bg.idClicked.connect(lambda _id, c=col: self._on_record_kind_changed(c))

            lab_scan = QLabel("Máy quét (USB–COM)")
            lab_scan.setToolTip(
                "Mỗi cổng hiển thị tên thiết bị (Windows) + hãng + mã VID:PID khi có — "
                "bấm «Làm mới camera & cổng COM» để quét lại sau khi cắm máy quét.\n"
                "Tốc độ Baud dùng mặc định trong cấu hình (thường 9600); cần khác thì chỉnh trong "
                "tệp cấu hình JSON (không hiện nút trên UI để tránh chỉnh nhầm)."
            )
            g.addWidget(lab_scan, 2, 0)
            sc = QComboBox()
            sc.setMinimumWidth(320)
            sc.setToolTip(
                "Chọn đúng máy quét: đọc cả dòng mô tả, không chỉ COMx. "
                "Ưu tiên cổng USB serial (thường lên đầu danh sách)."
            )
            sc.currentIndexChanged.connect(lambda _i, c=col: self._on_scanner_or_decode_changed(c))
            g.addWidget(sc, 2, 1)
            self._scanner.append(sc)

            dh = QLabel(
                "Khi chọn cổng COM ở trên, mã vạch đọc từ máy quét USB–serial.\n"
                "Để trống COM thì dùng camera đọc mã (pyzbar) bên dưới."
            )
            dh.setWordWrap(True)
            dh.setStyleSheet("color:#666;font-size:11px;")
            self._decode_hint.append(dh)
            form_l.addLayout(g)
            form_l.addWidget(dh)

            g3 = QGridLayout()
            g3.addWidget(QLabel("Tên máy"), 0, 0)
            ne = QLineEdit()
            ne.setPlaceholderText(f"Máy {col + 1}")
            ne.editingFinished.connect(lambda _c=col: self._on_station_name_finished())
            g3.addWidget(ne, 0, 1)
            self._name.append(ne)
            form_l.addLayout(g3)

            v.addWidget(form_w, 0)
            columns.addWidget(box, 1)

        root_layout = QVBoxLayout(self)
        root_layout.addWidget(self._top_bar, 0)
        root_layout.addLayout(columns, 1)

    def camera_indices_selected_in_ui(self) -> set[int]:
        return self._indices_from_combos()

    def _is_rtsp_column(self, col: int) -> bool:
        if not (0 <= col < len(self._record_kind)):
            return False
        return self._record_kind[col].checkedId() == 1

    def _apply_record_kind_visibility(self, col: int) -> None:
        if not (0 <= col < len(self._record)):
            return
        rtsp = self._is_rtsp_column(col)
        self._record[col].setVisible(not rtsp)
        self._rtsp_url[col].setVisible(rtsp)
        self._rtsp_connect_btn[col].setVisible(rtsp)

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
        if self._is_rtsp_column(other) and self._rtsp_url[other].text().strip():
            return None
        d = self._record[other].currentData()
        return int(d) if d is not None else None

    @staticmethod
    def _usb_index_for_sync(st: StationConfig, col: int) -> int:
        if st.record_camera_kind == "rtsp" and (st.record_rtsp_url or "").strip():
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
            self._repopulate_scanner_combo(self._scanner[col], port, probe_serial=True)

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
        self._cam_indices = sorted(set(probed or [0]) | self._indices_from_combos())
        pr0 = self._record[0].currentData()
        pr1 = self._record[1].currentData()
        sel0 = int(pr0) if pr0 is not None else self._cam_indices[0]
        sel1 = int(pr1) if pr1 is not None else self._cam_indices[min(1, len(self._cam_indices) - 1)]
        if sel0 not in self._cam_indices:
            sel0 = self._cam_indices[0]
        if sel1 not in self._cam_indices:
            sel1 = self._cam_indices[min(1, len(self._cam_indices) - 1)]
        if not self._is_rtsp_column(0) and not self._is_rtsp_column(1):
            if sel0 == sel1:
                alt = next((i for i in self._cam_indices if i != sel0), None)
                if alt is None:
                    alt = (sel0 + 1) % 10
                sel1 = alt
        if not self._is_rtsp_column(0):
            self._repopulate_record_combo(0, sel0)
        if not self._is_rtsp_column(1):
            self._repopulate_record_combo(1, sel1)

        for col in range(2):
            port = ""
            if self._scanner[col].count():
                d = self._scanner[col].currentData()
                port = str(d) if d else ""
            self._repopulate_scanner_combo(self._scanner[col], port, probe_serial=True)

            self._on_scanner_or_decode_changed(col, emit=False)

    def _emit_debounced(self) -> None:
        self._debounce.start()

    def _pick_root(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu video", self._root.text())
        if d:
            self._root.setText(d)
            self.fields_changed.emit()

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
        other = 1 - col
        other_idx = self._other_column_usb_index(other)
        allowed = [i for i in self._cam_indices if other_idx is None or i != other_idx]
        if not allowed:
            allowed = [i for i in range(10) if other_idx is None or i != other_idx]
        if select not in allowed:
            select = allowed[0]
        self._repopulate_camera_combo(self._record[col], allowed, select)

    def _repopulate_scanner_combo(
        self, combo: QComboBox, select_port: str, *, probe_serial: bool = True
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
                return
            sp = (select_port or "").strip()
            pairs = list_filtered_serial_ports(try_open_ports=probe_serial)
            listed = {d for d, _ in pairs}
            if sp and sp not in listed:
                combo.addItem(f"{sp} — (đã lưu trong cấu hình)", sp)
            for device, label in pairs:
                combo.addItem(label, device)
            idx = combo.findData(sp)
            if idx < 0:
                idx = 0
            combo.setCurrentIndex(idx)

    def _indices_from_combos(self) -> set[int]:
        out: set[int] = set()
        for col in range(2):
            if self._is_rtsp_column(col) and self._rtsp_url[col].text().strip():
                out.add(10 + col)
            else:
                d = self._record[col].currentData()
                if d is not None:
                    out.add(int(d))
        return out

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

    def sync_from_config(
        self,
        cfg: AppConfig,
        *,
        probed_override: list[int] | None = None,
        fast_serial_scan: bool = False,
    ) -> None:
        self._root.setText(cfg.video_root)
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
            is_rtsp = s.record_camera_kind == "rtsp" and (s.record_rtsp_url or "").strip()
            bg = self._record_kind[col]
            with QSignalBlocker(bg):
                if is_rtsp:
                    bg.button(1).setChecked(True)
                else:
                    bg.button(0).setChecked(True)
            self._rtsp_url[col].setText((s.record_rtsp_url or "").strip())
            self._apply_record_kind_visibility(col)
            self._repopulate_scanner_combo(
                self._scanner[col],
                (s.scanner_serial_port or "").strip(),
                probe_serial=not fast_serial_scan,
            )
            self._name[col].setText(s.packer_label)
            self._on_scanner_or_decode_changed(col, emit=False)
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

    def duplicate_scanner_ports(self) -> bool:
        raw = [
            str(self._scanner[i].currentData() or "").strip() for i in range(2)
        ]
        return bool(raw[0] and raw[0] == raw[1])

    def apply_to_config(self, cfg: AppConfig) -> None:
        cfg.video_root = self._root.text().strip()
        for col in range(min(2, len(cfg.stations))):
            s = cfg.stations[col]
            raw_port = self._scanner[col].currentData()
            port = ""
            if raw_port and str(raw_port).strip():
                port = str(raw_port).strip()
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
                preview_display_index=-1,
                record_roi_norm=self._preview[col].get_roi_norm(),
            )

    def set_cinema_mode(self, on: bool) -> None:
        """Phóng to cửa sổ: ẩn form, chỉ hai khung camera giãn full."""
        if self._cinema_mode == on:
            return
        self._cinema_mode = on
        self._top_bar.setVisible(not on)
        for fw in self._column_forms:
            fw.setVisible(not on)
        for i, box in enumerate(self._group_boxes):
            box.setFlat(on)
            box.setTitle("" if on else f"Máy {i + 1}")
        for prev in self._preview:
            prev.set_fast_scale(not on)
            if on:
                prev.setMinimumSize(240, 180)
                prev.setMaximumHeight(16_777_215)
                prev.setSizePolicy(
                    QSizePolicy.Policy.Expanding,
                    QSizePolicy.Policy.Expanding,
                )
            else:
                prev.setMinimumSize(360, 200)
                prev.setMaximumHeight(280)
                prev.setSizePolicy(
                    QSizePolicy.Policy.Preferred,
                    QSizePolicy.Policy.Preferred,
                )

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
        """Đưa tiêu điểm bàn phím vào ô mã đơn quầy 1 (máy quét kiểu wedge)."""
        if self._manual_col_order:
            self._manual_col_order[0].setFocus(Qt.FocusReason.ActiveWindowFocusReason)

    def clear_previews(self) -> None:
        for i in range(len(self._preview)):
            self.set_preview_column(i, None, 0, 0)

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
        """Hai quầy cùng camera đọc mã (camera = mã nguồn) khi không dùng COM."""
        indices: list[int] = []
        for col in range(2):
            port = self._scanner[col].currentData()
            if port and str(port).strip():
                continue
            if self._is_rtsp_column(col) and self._rtsp_url[col].text().strip():
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
        if not (0 <= col < len(self._manual_col_order)):
            return
        self._manual_col_order[col].clear()

    def _emit_manual_col(self, col: int) -> None:
        if not (0 <= col < len(self._manual_col_order)):
            return
        text = normalize_manual_order_text(self._manual_col_order[col].text())
        if not text:
            return
        self.manual_order_submitted.emit(col, text)

    def set_preview_column(
        self,
        col: int,
        bgr: bytes | None,
        src_w: int,
        src_h: int,
    ) -> None:
        if not (0 <= col < len(self._preview)):
            return
        lab = self._preview[col]
        if bgr is None or src_w <= 0 or src_h <= 0:
            lab.clear_frame()
        else:
            lab.set_full_frame_bgr(bgr, src_w, src_h)
