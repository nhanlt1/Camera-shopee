from __future__ import annotations

from dataclasses import replace
from typing import Optional

from PySide6.QtCore import QSignalBlocker, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from packrecorder.camera_probe import probe_opencv_camera_indices
from packrecorder.config import AppConfig, StationConfig
from packrecorder.order_input import normalize_manual_order_text
from packrecorder.serial_ports import iter_raw_comports, list_filtered_serial_ports


def _station_camera_indices(stations: list[StationConfig]) -> set[int]:
    """Index camera đang dùng trong cấu hình (luôn đưa vào combo dù probe không thấy)."""
    out: set[int] = set()
    for s in stations[:2]:
        out.add(int(s.record_camera_index))
        out.add(int(s.decode_camera_index))
    return out


def _merge_probe_with_config(probed: list[int], cfg: AppConfig) -> list[int]:
    base = set(probed) if probed else {0}
    base |= _station_camera_indices(list(cfg.stations))
    return sorted(base)


class DualStationWidget(QWidget):
    """Hai cột: camera ghi, máy quét COM (USB serial), hoặc camera đọc mã."""

    fields_changed = Signal()
    refresh_devices_requested = Signal()
    manual_order_submitted = Signal(int, str)

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

        self._preview: list[QLabel] = []
        self._record_banner: list[QLabel] = []
        self._record_elapsed: list[QLabel] = []
        self._group_boxes: list[QGroupBox] = []
        self._column_forms: list[QWidget] = []
        self._record: list[QComboBox] = []
        self._scanner: list[QComboBox] = []
        self._baud: list[QSpinBox] = []
        self._decode: list[QComboBox] = []
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
            banner.setWordWrap(True)
            banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
            banner.setStyleSheet(
                "background-color:#c8e6c9;color:#1b5e20;padding:10px 8px;"
                "font-size:13px;font-weight:bold;border-radius:6px;border:2px solid #2e7d32;"
            )
            self._record_banner.append(banner)
            v.addWidget(banner, 0)

            elapsed = QLabel()
            elapsed.setVisible(False)
            elapsed.setAlignment(Qt.AlignmentFlag.AlignCenter)
            elapsed.setWordWrap(True)
            elapsed.setStyleSheet(
                "background-color:#ffebee;color:#b71c1c;padding:8px 6px;"
                "font-size:20px;font-weight:bold;border-radius:6px;"
                "font-family:Consolas,'Cascadia Mono','Segoe UI Mono',monospace;"
                "border:2px solid #c62828;"
            )
            self._record_elapsed.append(elapsed)
            v.addWidget(elapsed, 0)

            row_m = QHBoxLayout()
            row_m.setContentsMargins(0, 4, 0, 0)
            mo = QLineEdit()
            mo.setPlaceholderText(
                f"Máy {col + 1}: quét mã (điền + Enter) — lần 1 ghi, lần 2 cùng mã dừng."
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

            prev = QLabel()
            prev.setMinimumSize(360, 200)
            prev.setMaximumHeight(280)
            prev.setAlignment(Qt.AlignmentFlag.AlignCenter)
            prev.setScaledContents(False)
            prev.setStyleSheet(
                "background:#1a1a1a;color:#888;border:1px solid #424242;border-radius:6px;"
            )
            prev.setText("Chưa có hình")
            self._preview.append(prev)
            v.addWidget(prev, 1)

            form_w = QWidget()
            form_l = QVBoxLayout(form_w)
            form_l.setContentsMargins(0, 0, 0, 0)
            self._column_forms.append(form_w)

            g = QGridLayout()
            g.addWidget(QLabel("Camera ghi hình"), 0, 0)
            rc = QComboBox()
            rc.currentIndexChanged.connect(lambda _i, c=col: self._on_record_changed(c))
            g.addWidget(rc, 0, 1)
            self._record.append(rc)

            g.addWidget(QLabel("Máy quét (USB–COM)"), 1, 0)
            sc = QComboBox()
            sc.setMinimumWidth(220)
            sc.currentIndexChanged.connect(lambda _i, c=col: self._on_scanner_or_decode_changed(c))
            g.addWidget(sc, 1, 1)
            self._scanner.append(sc)

            g.addWidget(QLabel("Baud máy quét"), 2, 0)
            baud = QSpinBox()
            baud.setRange(1200, 921600)
            baud.setSingleStep(1200)
            baud.setValue(9600)
            baud.valueChanged.connect(self._emit_debounced)
            g.addWidget(baud, 2, 1)
            self._baud.append(baud)

            dh = QLabel(
                "Khi chọn cổng COM ở trên, mã vạch đọc từ máy quét USB–serial.\n"
                "Để trống COM thì dùng camera đọc mã (pyzbar) bên dưới."
            )
            dh.setWordWrap(True)
            dh.setStyleSheet("color:#666;font-size:11px;")
            self._decode_hint.append(dh)
            form_l.addLayout(g)
            form_l.addWidget(dh)

            g2 = QGridLayout()
            g2.addWidget(QLabel("Camera đọc mã"), 0, 0)
            dc = QComboBox()
            dc.currentIndexChanged.connect(self._emit_debounced)
            g2.addWidget(dc, 0, 1)
            self._decode.append(dc)
            form_l.addLayout(g2)

            g3 = QGridLayout()
            g3.addWidget(QLabel("Tên máy"), 0, 0)
            ne = QLineEdit()
            ne.setPlaceholderText(f"Máy {col + 1}")
            ne.editingFinished.connect(self._emit_debounced)
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
        if sel0 == sel1:
            alt = next((i for i in self._cam_indices if i != sel0), None)
            if alt is None:
                alt = (sel0 + 1) % 10
            sel1 = alt
        self._repopulate_record_combo(0, sel0)
        self._repopulate_record_combo(1, sel1)

        for col in range(2):
            port = ""
            if self._scanner[col].count():
                d = self._scanner[col].currentData()
                port = str(d) if d else ""
            self._repopulate_scanner_combo(self._scanner[col], port, probe_serial=True)

            sel_r = int(self._record[col].currentData() or 0)
            prev_d = self._decode[col].currentData()
            sel_d = int(prev_d) if prev_d is not None else sel_r
            if sel_d not in self._cam_indices:
                sel_d = self._cam_indices[min(1, len(self._cam_indices) - 1)]
            self._repopulate_camera_combo(self._decode[col], self._cam_indices, sel_d)

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
        od = self._record[other].currentData()
        other_idx = int(od) if od is not None else None
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
            for combo in (self._record[col], self._decode[col]):
                d = combo.currentData()
                if d is not None:
                    out.add(int(d))
        return out

    def refresh_device_lists(self) -> None:
        """Probe đồng bộ — chỉ dùng khi không có UI thread (test); UI dùng probe nền + apply_camera_probe_result."""
        probed = probe_opencv_camera_indices(max_index=6, require_frame=False)
        self.apply_camera_probe_result(probed)

    def _on_record_changed(self, col: int) -> None:
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
        self._decode[col].setEnabled(not use_serial)
        self._baud[col].setEnabled(use_serial)
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
        r0 = cfg.stations[0].record_camera_index if len(cfg.stations) > 0 else 0
        r1 = cfg.stations[1].record_camera_index if len(cfg.stations) > 1 else 1
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
            d = s.decode_camera_index
            if d not in self._cam_indices:
                d = self._cam_indices[min(1, len(self._cam_indices) - 1)]
            self._repopulate_scanner_combo(
                self._scanner[col],
                (s.scanner_serial_port or "").strip(),
                probe_serial=not fast_serial_scan,
            )
            self._repopulate_camera_combo(self._decode[col], self._cam_indices, d)
            with QSignalBlocker(self._baud[col]):
                self._baud[col].setValue(s.scanner_serial_baud)
            self._name[col].setText(s.packer_label)
            self._on_scanner_or_decode_changed(col, emit=False)

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
            rd = self._record[col].currentData()
            dd = self._decode[col].currentData()
            cfg.stations[col] = replace(
                s,
                packer_label=(self._name[col].text().strip() or f"Máy {col + 1}"),
                record_camera_index=int(rd) if rd is not None else 0,
                decode_camera_index=int(dd) if dd is not None else 0,
                scanner_serial_port=port,
                scanner_serial_baud=int(self._baud[col].value()),
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

    def clear_previews(self) -> None:
        for i in range(len(self._preview)):
            self.set_preview_column(i, None)

    def set_column_recording_banner(self, col: int, text: str | None) -> None:
        """Banner phía trên preview: đang ghi / ẩn (None). Luôn thấy khi cinema."""
        if not (0 <= col < len(self._record_banner)):
            return
        lab = self._record_banner[col]
        if text:
            lab.setText(text)
            lab.setVisible(True)
        else:
            lab.clear()
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

    def _pixmap_letterbox_label(self, lab: QLabel, pix: QPixmap) -> QPixmap:
        """Cinema: fit trong khung, giữ tỉ lệ gốc, viền đen (không crop)."""
        dpr = float(lab.devicePixelRatioF()) or 1.0
        tw = max(1, int(lab.width() * dpr))
        th = max(1, int(lab.height() * dpr))
        if pix.isNull() or lab.width() < 8 or lab.height() < 8:
            return pix
        scaled = pix.scaled(
            tw,
            th,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        canvas = QPixmap(tw, th)
        canvas.fill(QColor(0x1A, 0x1A, 0x1A))
        painter = QPainter(canvas)
        x = (tw - scaled.width()) // 2
        y = (th - scaled.height()) // 2
        painter.drawPixmap(x, y, scaled)
        painter.end()
        canvas.setDevicePixelRatio(dpr)
        return canvas

    def has_decode_camera_collision(self) -> bool:
        """Hai quầy cùng «Camera đọc mã» khi cả hai đều không dùng COM — dễ gán sai quầy."""
        indices: list[int] = []
        for col in range(2):
            port = self._scanner[col].currentData()
            if port and str(port).strip():
                continue
            dd = self._decode[col].currentData()
            if dd is not None:
                indices.append(int(dd))
        return len(indices) == 2 and indices[0] == indices[1]

    def has_decode_on_peer_record_collision(self) -> bool:
        """«Camera đọc mã» trùng «Camera ghi» của quầy kia — pyzbar đọc nhầm khi quầy kia dùng COM."""
        for col in range(2):
            port = self._scanner[col].currentData()
            if port and str(port).strip():
                continue
            dd = self._decode[col].currentData()
            if dd is None:
                continue
            dec = int(dd)
            od = self._record[1 - col].currentData()
            if od is not None and int(od) == dec:
                return True
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

    def set_preview_column(self, col: int, pixmap: Optional[QPixmap]) -> None:
        if not (0 <= col < len(self._preview)):
            return
        lab = self._preview[col]
        if pixmap is None or pixmap.isNull():
            lab.clear()
            lab.setText("Chưa có hình")
        else:
            disp = self._pixmap_letterbox_label(lab, pixmap) if self._cinema_mode else pixmap
            lab.setPixmap(disp)
            lab.setText("")
