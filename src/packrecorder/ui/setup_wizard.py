from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
    QWizard,
    QWizardPage,
)

from packrecorder.camera_probe import probe_opencv_camera_indices
from packrecorder.config import (
    AppConfig,
    StationConfig,
    ensure_dual_stations,
    normalize_config,
)
from packrecorder.serial_ports import list_filtered_serial_ports
from packrecorder.ui.dual_station_widget import (
    DualStationWidget,
    RTSP_DEFAULT_URL_BY_COLUMN,
    _merge_probe_with_config,
)
from packrecorder.ui.setup_wizard_camera import apply_wizard_camera_station
from packrecorder.ui.setup_wizard_preview import SingleFramePreviewThread
from packrecorder.ui.hid_pos_setup_wizard import HidPosSetupWizard
from packrecorder.ui.setup_wizard_scanner import (
    apply_scanner_choice_camera_decode,
    apply_scanner_choice_com,
    apply_scanner_choice_hid,
    apply_scanner_choice_keyboard_wedge,
    auto_apply_background_scanner,
)
from packrecorder.ui.winson_com_qr_panel import WinsonComQrPanel


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def filter_camera_indices_for_wizard(
    indices: list[int],
    cfg: AppConfig,
    col: int,
) -> list[int]:
    if col != 1 or not cfg.stations:
        return list(indices)
    st0 = cfg.stations[0]
    if st0.record_camera_kind != "usb":
        return list(indices)
    used = int(st0.record_camera_index)
    return [i for i in indices if int(i) != used]


def filter_com_ports_for_wizard(
    ports: list[tuple[str, str]],
    cfg: AppConfig,
    col: int,
) -> list[tuple[str, str]]:
    if col != 1 or not cfg.stations:
        return list(ports)
    used = (cfg.stations[0].scanner_serial_port or "").strip()
    if not used:
        return list(ports)
    out: list[tuple[str, str]] = []
    for dev, label in ports:
        if (dev or "").strip() != used:
            out.append((dev, label))
    return out


def scanner_default_mode_id(st: StationConfig) -> int:
    """Map scanner_input_kind -> top-level mode in WizardScannerPage.

    0: visible (Máy quét thông thường — wedge / camera decode)
    1: background (Máy quét chạy ẩn — COM / HID POS)
    """
    kind = getattr(st, "scanner_input_kind", "com")
    if kind in ("keyboard", "camera"):
        return 0
    if kind == "hid_pos":
        return 1
    if kind == "com" and (st.scanner_serial_port or "").strip():
        return 1
    if kind == "com":
        return 0
    return 1


def scanner_default_visible_subkind(st: StationConfig) -> str:
    """Sub-option khi station đang ở chế độ «thông thường»: keyboard | camera."""
    kind = getattr(st, "scanner_input_kind", "com")
    if kind == "camera":
        return "camera"
    if kind == "keyboard":
        return "keyboard"
    return "keyboard"


class IntroStationCountPage(QWizardPage):
    def __init__(self, cfg: AppConfig, parent: QWizard) -> None:
        super().__init__(parent)
        self.setTitle("Số quầy")
        self._cfg = cfg
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Chọn số quầy vận hành:"))
        self._g = QButtonGroup(self)
        self._r1 = QRadioButton("Một quầy")
        self._r2 = QRadioButton("Hai quầy")
        self._r2.setChecked(True)
        self._g.addButton(self._r1, 1)
        self._g.addButton(self._r2, 2)
        lay.addWidget(self._r1)
        lay.addWidget(self._r2)

    def validatePage(self) -> bool:
        wiz = self.wizard()
        assert isinstance(wiz, SetupWizard)
        n = self._g.checkedId()
        if n == 1:
            wiz._two_stations = False
            wiz._cfg.stations = wiz._cfg.stations[:1]
        else:
            wiz._two_stations = True
            ensure_dual_stations(wiz._cfg)
        return True


class WizardCameraPage(QWizardPage):
    def __init__(self, col: int, parent: QWizard) -> None:
        super().__init__(parent)
        self._col = col
        self.setTitle(f"Máy {col + 1} — Camera")
        self._radio_usb = QRadioButton("USB webcam")
        self._radio_rtsp = QRadioButton("Camera IP (RTSP) — nâng cao")
        self._cam_kind = QButtonGroup(self)
        self._cam_kind.addButton(self._radio_usb, 0)
        self._cam_kind.addButton(self._radio_rtsp, 1)
        self._cam_kind.idClicked.connect(self._on_cam_kind_clicked)

        self._combo = QComboBox()
        usb_row = QHBoxLayout()
        usb_row.addWidget(self._combo, 1)
        self._btn_usb_preview = QPushButton("Xem trước USB")
        self._btn_usb_preview.setToolTip("Chụp 1 khung hình từ camera USB đang chọn.")
        self._btn_usb_preview.clicked.connect(self._on_usb_preview)
        usb_row.addWidget(self._btn_usb_preview)
        btn_usb_refresh = QPushButton("Làm mới danh sách camera")
        btn_usb_refresh.setToolTip("Quét lại webcam đã cắm (tương tự màn Quầy).")
        btn_usb_refresh.clicked.connect(self._on_usb_refresh_cameras)
        usb_row.addWidget(btn_usb_refresh)
        usb_form = QFormLayout()
        usb_row_w = QWidget()
        usb_row_w.setLayout(usb_row)
        usb_form.addRow("Camera ghi (USB index):", usb_row_w)
        w_usb = QWidget()
        w_usb.setLayout(usb_form)

        self._rtsp_url = QLineEdit()
        self._rtsp_url.setPlaceholderText(RTSP_DEFAULT_URL_BY_COLUMN[col])
        btn_rtsp_hint = QPushButton("Hướng dẫn kết nối RTSP…")
        btn_rtsp_hint.clicked.connect(self._on_rtsp_connection_hint)
        self._btn_rtsp_test = QPushButton("Thử kết nối + xem trước RTSP")
        self._btn_rtsp_test.setToolTip(
            "Mở luồng RTSP ngắn, chụp 1 khung hình rồi đóng ngay."
        )
        self._btn_rtsp_test.clicked.connect(self._on_test_rtsp_connection)
        rtsp_form = QFormLayout()
        rtsp_form.addRow("URL RTSP:", self._rtsp_url)
        rtsp_form.addRow(self._btn_rtsp_test)
        rtsp_form.addRow(btn_rtsp_hint)
        w_rtsp = QWidget()
        w_rtsp.setLayout(rtsp_form)

        self._stack = QStackedWidget()
        self._stack.addWidget(w_usb)
        self._stack.addWidget(w_rtsp)

        hint = QLabel(
            "RTSP: cần mạng ổn định; có thể chỉnh sau trong Cài đặt hoặc màn Quầy."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#555;font-size:12px;")

        outer = QVBoxLayout(self)
        outer.addWidget(self._radio_usb)
        outer.addWidget(self._radio_rtsp)
        outer.addWidget(self._stack)
        self._preview_label = QLabel("Chưa có ảnh xem trước.")
        self._preview_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview_label.setMinimumHeight(180)
        self._preview_label.setStyleSheet(
            "border:1px solid #cfd8dc;border-radius:4px;background:#fafafa;color:#607d8b;padding:8px;"
        )
        outer.addWidget(self._preview_label)
        outer.addWidget(hint)
        self._preview_thread: SingleFramePreviewThread | None = None

    def _on_cam_kind_clicked(self, _bid: int) -> None:
        self._stack.setCurrentIndex(1 if self._radio_rtsp.isChecked() else 0)

    def _refill_usb_camera_combo(self, preferred_index: int | None) -> None:
        wiz = self.wizard()
        assert isinstance(wiz, SetupWizard)
        cfg = wiz._cfg
        probed = probe_opencv_camera_indices(max_index=6, require_frame=False)
        indices = _merge_probe_with_config(probed, cfg)
        indices = filter_camera_indices_for_wizard(indices, cfg, self._col)
        self._combo.clear()
        if not indices:
            self._combo.addItem("(Không còn camera USB khả dụng)", None)
            self._combo.setCurrentIndex(0)
            return
        for i in indices:
            self._combo.addItem(f"Camera {i}", i)
        st = cfg.stations[self._col]
        want = (
            int(preferred_index)
            if preferred_index is not None
            else (
                int(st.record_camera_index)
                if st.record_camera_kind == "usb"
                else 0
            )
        )
        idx = self._combo.findData(want)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        elif self._combo.count() > 0:
            self._combo.setCurrentIndex(0)

    def _on_usb_refresh_cameras(self) -> None:
        if not self._radio_usb.isChecked():
            return
        keep = self._combo.currentData()
        pref = int(keep) if keep is not None else None
        self._refill_usb_camera_combo(pref)

    def _on_rtsp_connection_hint(self) -> None:
        QMessageBox.information(
            self,
            "RTSP",
            "Sau khi hoàn tất Wizard, trên màn Quầy hãy chọn «RTSP (IP)», "
            "nhập URL và bấm «Kết nối RTSP». Có thể chỉnh thêm trong Cài đặt hoặc file cấu hình.",
        )

    def _set_preview_busy(self, on: bool) -> None:
        busy = bool(on)
        self._btn_usb_preview.setEnabled(not busy)
        self._btn_rtsp_test.setEnabled(not busy)
        if busy:
            self._preview_label.setText("Đang lấy ảnh xem trước…")

    def _start_preview(self, th: SingleFramePreviewThread) -> None:
        if self._preview_thread is not None and self._preview_thread.isRunning():
            QMessageBox.information(self, "Xem trước", "Đang lấy ảnh xem trước, chờ chút…")
            return
        self._preview_thread = th
        self._set_preview_busy(True)
        th.preview_ready.connect(self._on_preview_ready)
        th.finished.connect(lambda: self._set_preview_busy(False))
        th.start()

    def _on_usb_preview(self) -> None:
        rd = self._combo.currentData()
        if rd is None:
            QMessageBox.warning(self, "USB", "Không có camera USB để xem trước.")
            return
        self._start_preview(SingleFramePreviewThread.for_usb(int(rd), self))

    def _on_test_rtsp_connection(self) -> None:
        self._start_preview(SingleFramePreviewThread.for_rtsp(self._rtsp_url.text(), self))

    def _on_preview_ready(self, ok: bool, msg: str, image_obj: object) -> None:
        if ok and image_obj is not None:
            pix = QPixmap.fromImage(image_obj)
            self._preview_label.setPixmap(
                pix.scaled(
                    420,
                    220,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
            self._preview_label.setToolTip(msg)
            return
        self._preview_label.setPixmap(QPixmap())
        self._preview_label.setText(msg)

    def initializePage(self) -> None:
        wiz = self.wizard()
        assert isinstance(wiz, SetupWizard)
        cfg = wiz._cfg
        st = cfg.stations[self._col]
        is_rtsp = st.record_camera_kind == "rtsp" and (st.record_rtsp_url or "").strip()
        if is_rtsp:
            self._radio_rtsp.setChecked(True)
            self._rtsp_url.setText((st.record_rtsp_url or "").strip())
            self._stack.setCurrentIndex(1)
            self._refill_usb_camera_combo(None)
        else:
            self._radio_usb.setChecked(True)
            self._stack.setCurrentIndex(0)
            want = int(st.record_camera_index) if st.record_camera_kind == "usb" else 0
            self._refill_usb_camera_combo(want)

    def validatePage(self) -> bool:
        wiz = self.wizard()
        assert isinstance(wiz, SetupWizard)
        st = wiz._cfg.stations[self._col]
        if self._radio_usb.isChecked():
            rd = self._combo.currentData()
            if rd is None:
                QMessageBox.warning(
                    self,
                    "Camera USB",
                    "Không còn camera USB để chọn cho Máy 2 (đang dùng ở Máy 1).",
                )
                return False
            rec = int(rd) if rd is not None else 0
            wiz._cfg.stations[self._col] = apply_wizard_camera_station(
                st, self._col, use_usb=True, usb_index=rec, rtsp_url=""
            )
            return True
        url = self._rtsp_url.text().strip()
        if not url:
            QMessageBox.warning(
                self,
                "RTSP",
                "Nhập URL RTSP hoặc chọn USB webcam.",
            )
            return False
        try:
            wiz._cfg.stations[self._col] = apply_wizard_camera_station(
                st, self._col, use_usb=False, usb_index=0, rtsp_url=url
            )
        except ValueError:
            return False
        return True


class WizardScannerPage(QWizardPage):
    """Trang chọn máy quét — 2 chế độ chính:

    - Visible (mode 0): Máy quét «thông thường» — cần app focus liên tục.
      Sub-option: keyboard wedge (mặc định) hoặc camera decode (pyzbar).
    - Background (mode 1): Máy quét «chạy ẩn» — chạy nền, app không cần focus.
      Auto-detect COM trước; nếu không có COM thì hiện QR Winson; quét xong
      vẫn không có COM thì mở HidPosSetupWizard để chọn HID POS.
    """

    MODE_VISIBLE = 0
    MODE_BACKGROUND = 1

    def __init__(self, col: int, parent: QWizard) -> None:
        super().__init__(parent)
        self._col = col
        self.setTitle(f"Máy {col + 1} — Máy quét")
        self._hid_vid: str | None = None
        self._hid_pid: str | None = None
        self._auto_com_port: str = ""

        self._radio_visible = QRadioButton(
            "Máy quét thông thường — yêu cầu mở app liên tục để nhận"
        )
        self._radio_background = QRadioButton(
            "Máy quét chạy ẩn — không cần mở app liên tục"
        )
        self._mode_grp = QButtonGroup(self)
        self._mode_grp.addButton(self._radio_visible, self.MODE_VISIBLE)
        self._mode_grp.addButton(self._radio_background, self.MODE_BACKGROUND)
        self._mode_grp.idClicked.connect(self._on_mode_changed)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_visible_page())
        self._stack.addWidget(self._build_background_page())

        outer = QVBoxLayout(self)
        outer.addWidget(
            QLabel("Chọn cách máy quét gửi mã đơn về phần mềm:")
        )
        outer.addWidget(self._radio_visible)
        outer.addWidget(self._radio_background)
        outer.addWidget(self._stack, 1)

    def _build_visible_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        intro = QLabel(
            "App phải đang mở (cửa sổ chính hiện trên màn) để nhận mã. "
            "Phù hợp khi máy quét xuất ra phím như bàn phím, hoặc bạn muốn "
            "đọc mã bằng camera đặt tại quầy."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#455a64;")
        lay.addWidget(intro)

        self._sub_wedge = QRadioButton(
            "Máy quét gõ phím — gõ mã vào ô «Mã đơn» rồi Enter (HID keyboard)"
        )
        self._sub_camera = QRadioButton(
            "Đọc mã bằng camera ghi (pyzbar) — không cần máy quét rời"
        )
        self._sub_wedge.setChecked(True)
        self._sub_grp = QButtonGroup(page)
        self._sub_grp.addButton(self._sub_wedge, 0)
        self._sub_grp.addButton(self._sub_camera, 1)
        lay.addWidget(self._sub_wedge)
        lay.addWidget(self._sub_camera)

        hint = QLabel(
            "Lưu ý: chế độ này yêu cầu cửa sổ Pack Recorder hoạt động — "
            "nếu thu vào khay/ẩn cửa sổ thì có thể bỏ sót mã."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#7f6000;font-size:12px;")
        lay.addWidget(hint)
        lay.addStretch(1)
        return page

    def _build_background_page(self) -> QWidget:
        page = QWidget()
        lay = QVBoxLayout(page)
        intro = QLabel(
            "Máy quét gửi mã trực tiếp về phần mềm ngay cả khi cửa sổ ẩn / thu khay. "
            "App sẽ tự ưu tiên cổng COM (USB serial) — nếu không thấy, hướng dẫn "
            "quét QR Winson để chuyển scanner sang COM."
        )
        intro.setWordWrap(True)
        intro.setStyleSheet("color:#455a64;")
        lay.addWidget(intro)

        self._lbl_bg_status = QLabel("")
        self._lbl_bg_status.setWordWrap(True)
        self._lbl_bg_status.setStyleSheet("font-weight:600;")
        lay.addWidget(self._lbl_bg_status)

        row = QHBoxLayout()
        self._btn_bg_refresh = QPushButton("Quét lại thiết bị")
        self._btn_bg_refresh.clicked.connect(self._refresh_background_state)
        self._btn_bg_open_hid = QPushButton("Cấu hình HID POS thủ công…")
        self._btn_bg_open_hid.clicked.connect(self._run_hid_wizard)
        row.addWidget(self._btn_bg_refresh)
        row.addWidget(self._btn_bg_open_hid)
        row.addStretch(1)
        lay.addLayout(row)

        self._qr = WinsonComQrPanel(_repo_root(), page)
        self._qr.set_on_refresh(self._refresh_background_state)
        lay.addWidget(self._qr)
        lay.addStretch(1)
        return page

    def _on_mode_changed(self, mode_id: int) -> None:
        self._stack.setCurrentIndex(mode_id)
        if mode_id == self.MODE_BACKGROUND:
            self._refresh_background_state()

    def _refresh_background_state(self) -> None:
        wiz = self.wizard()
        if not isinstance(wiz, SetupWizard):
            return
        raw = list_filtered_serial_ports(try_open_ports=True)
        raw = filter_com_ports_for_wizard(raw, wiz._cfg, self._col)
        if raw:
            prev = (wiz._cfg.stations[self._col].scanner_serial_port or "").strip()
            chosen = ""
            chosen_label = ""
            if prev:
                for dev, label in raw:
                    if (dev or "").strip() == prev:
                        chosen = prev
                        chosen_label = label
                        break
            if not chosen:
                chosen = (raw[0][0] or "").strip()
                chosen_label = raw[0][1]
            self._auto_com_port = chosen
            self._lbl_bg_status.setText(
                f"Đã phát hiện cổng COM: {chosen_label} — sẽ dùng tự động."
            )
            self._qr.setVisible(False)
            self._btn_bg_open_hid.setVisible(False)
        else:
            self._auto_com_port = ""
            has_hid = bool(self._hid_vid and self._hid_pid)
            if has_hid:
                self._lbl_bg_status.setText(
                    f"Không thấy cổng COM. Sẽ dùng HID POS đã cấu hình "
                    f"(VID {self._hid_vid} / PID {self._hid_pid})."
                )
            else:
                self._lbl_bg_status.setText(
                    "Chưa thấy cổng COM. Quét QR Winson dưới đây để chuyển scanner sang COM, "
                    "rồi bấm «Quét lại thiết bị». Nếu scanner không hỗ trợ COM, dùng "
                    "«Cấu hình HID POS thủ công…»."
                )
            self._qr.setVisible(True)
            self._btn_bg_open_hid.setVisible(True)

    def _run_hid_wizard(self) -> None:
        wiz = HidPosSetupWizard(self)
        chosen_vid: list[str] = []
        chosen_pid: list[str] = []

        def on_vid_pid(v: int, p: int) -> None:
            chosen_vid[:] = [f"{v:04X}"]
            chosen_pid[:] = [f"{p:04X}"]

        wiz.vid_pid_chosen.connect(on_vid_pid)
        if wiz.exec() == QDialog.DialogCode.Accepted and chosen_vid and chosen_pid:
            self._hid_vid = chosen_vid[0]
            self._hid_pid = chosen_pid[0]
            self._refresh_background_state()

    def initializePage(self) -> None:
        self._sync_mode_from_cfg()

    def _sync_mode_from_cfg(self) -> None:
        wiz = self.wizard()
        assert isinstance(wiz, SetupWizard)
        st = wiz._cfg.stations[self._col]
        self._mode_grp.blockSignals(True)
        try:
            mode_id = scanner_default_mode_id(st)
            sub = scanner_default_visible_subkind(st)
            if mode_id == self.MODE_VISIBLE:
                self._radio_visible.setChecked(True)
                self._stack.setCurrentIndex(self.MODE_VISIBLE)
                if sub == "camera":
                    self._sub_camera.setChecked(True)
                else:
                    self._sub_wedge.setChecked(True)
            else:
                self._radio_background.setChecked(True)
                self._stack.setCurrentIndex(self.MODE_BACKGROUND)
                self._hid_vid = (st.scanner_usb_vid or "").strip().upper() or None
                self._hid_pid = (st.scanner_usb_pid or "").strip().upper() or None
                self._refresh_background_state()
        finally:
            self._mode_grp.blockSignals(False)

    def validatePage(self) -> bool:
        wiz = self.wizard()
        assert isinstance(wiz, SetupWizard)
        st = wiz._cfg.stations[self._col]
        if self._radio_visible.isChecked():
            if self._sub_camera.isChecked():
                wiz._cfg.stations[self._col] = apply_scanner_choice_camera_decode(st)
            else:
                wiz._cfg.stations[self._col] = apply_scanner_choice_keyboard_wedge(st)
            return True
        # Background mode
        if self._auto_com_port:
            wiz._cfg.stations[self._col] = apply_scanner_choice_com(
                st, port=self._auto_com_port
            )
            return True
        if self._hid_vid and self._hid_pid:
            wiz._cfg.stations[self._col] = apply_scanner_choice_hid(
                st, vid=self._hid_vid, pid=self._hid_pid
            )
            return True
        QMessageBox.warning(
            self,
            "Máy quét chạy ẩn",
            "Chưa có cổng COM khả dụng và chưa cấu hình HID POS. "
            "Hãy quét QR Winson để chuyển scanner sang COM, rồi bấm «Quét lại thiết bị»; "
            "hoặc bấm «Cấu hình HID POS thủ công…» để chọn thiết bị HID.",
        )
        return False


class WizardNamePage(QWizardPage):
    def __init__(self, col: int, parent: QWizard) -> None:
        super().__init__(parent)
        self._col = col
        self.setTitle(f"Máy {col + 1} — Tên quầy")
        self._edit = QLineEdit()
        form = QFormLayout()
        form.addRow("Tên hiển thị:", self._edit)
        outer = QVBoxLayout(self)
        outer.addLayout(form)

    def initializePage(self) -> None:
        wiz = self.wizard()
        assert isinstance(wiz, SetupWizard)
        self._edit.setText(wiz._cfg.stations[self._col].packer_label)

    def validatePage(self) -> bool:
        wiz = self.wizard()
        assert isinstance(wiz, SetupWizard)
        label = self._edit.text().strip() or f"Máy {self._col + 1}"
        st = wiz._cfg.stations[self._col]
        wiz._cfg.stations[self._col] = replace(st, packer_label=label)
        last = len(wiz._cfg.stations) - 1
        if self._col != last:
            return True
        dw = DualStationWidget(kiosk_mode=False)
        dw.sync_from_config(wiz._cfg, probed_override=[], fast_serial_scan=True)
        if dw.duplicate_scanner_ports():
            QMessageBox.warning(
                wiz,
                "Trùng cổng máy quét",
                "Hai quầy đang chọn cùng một cổng — chỉnh lại.",
            )
            return False
        if dw.has_decode_on_peer_record_collision():
            QMessageBox.warning(
                wiz,
                "Xung đột camera đọc mã",
                "Điều chỉnh camera đọc mã / máy quét.",
            )
            return False
        return True


class SetupWizard(QWizard):
    """Thiết lập quầy nhiều bước + QR Winson khi không có COM (spec §6.3 / §12)."""

    def __init__(self, cfg: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setWindowTitle("Thiết lập máy & quầy")
        self.resize(720, 520)
        self._cfg = normalize_config(cfg)
        ensure_dual_stations(self._cfg)
        self._two_stations = True

        self.setPage(0, IntroStationCountPage(self._cfg, self))
        self.setPage(1, WizardCameraPage(0, self))
        self.setPage(2, WizardScannerPage(0, self))
        self.setPage(3, WizardNamePage(0, self))
        self.setPage(4, WizardCameraPage(1, self))
        self.setPage(5, WizardScannerPage(1, self))
        self.setPage(6, WizardNamePage(1, self))

    def nextId(self) -> int:  # noqa: N802
        cur = self.currentId()
        if cur == 0:
            return 1
        if cur == 1:
            return 2
        if cur == 2:
            return 3
        if cur == 3:
            return 4 if self._two_stations else -1
        if cur == 4:
            return 5
        if cur == 5:
            return 6
        if cur == 6:
            return -1
        return -1

    def previousId(self) -> int:  # noqa: N802
        cur = self.currentId()
        if cur == 1:
            return 0
        if cur == 2:
            return 1
        if cur == 3:
            return 2
        if cur == 4:
            return 3
        if cur == 5:
            return 4
        if cur == 6:
            return 5
        return -1

    def accept(self) -> None:
        self._cfg = normalize_config(self._cfg)
        self._cfg.onboarding_complete = True
        self._cfg.first_run_setup_required = False
        super().accept()

    def result_config(self) -> AppConfig:
        return normalize_config(self._cfg)


# Tương thích import cũ
SetupWizardDialog = SetupWizard
