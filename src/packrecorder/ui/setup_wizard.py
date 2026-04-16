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
from packrecorder.config import AppConfig, ensure_dual_stations, normalize_config
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
    """0: COM, 1: HID, 2: camera decode (manual chọn)."""
    if st.scanner_input_kind == "hid_pos" and (st.scanner_usb_vid or "").strip():
        return 1
    # UX mới: mặc định COM cho thao tác vận hành kho.
    return 0


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
    def __init__(self, col: int, parent: QWizard) -> None:
        super().__init__(parent)
        self._col = col
        self.setTitle(f"Máy {col + 1} — Máy quét")
        self._hid_vid: str | None = None
        self._hid_pid: str | None = None

        self._radio_com = QRadioButton("USB COM (khuyến nghị — pyserial)")
        self._radio_hid = QRadioButton("HID POS (đọc raw — VID/PID)")
        self._radio_cam = QRadioButton("Đọc mã bằng camera (không COM/HID)")
        self._mode_grp = QButtonGroup(self)
        self._mode_grp.addButton(self._radio_com, 0)
        self._mode_grp.addButton(self._radio_hid, 1)
        self._mode_grp.addButton(self._radio_cam, 2)
        self._mode_grp.idClicked.connect(self._on_mode_id)

        self._combo = QComboBox()
        self._combo.setMinimumWidth(320)
        btn_refresh = QPushButton("Làm mới thiết bị")
        btn_refresh.clicked.connect(self._refresh_ports)
        self._qr = WinsonComQrPanel(_repo_root(), self)
        self._qr.set_on_refresh(self._refresh_ports)
        com_form = QFormLayout()
        com_form.addRow("Cổng COM:", self._combo)
        com_form.addRow(btn_refresh)
        w_com = QWidget()
        w_com_l = QVBoxLayout(w_com)
        w_com_l.addLayout(com_form)
        w_com_l.addWidget(self._qr)

        btn_hid = QPushButton("Mở thiết lập HID POS…")
        btn_hid.clicked.connect(self._run_hid_wizard)
        self._lbl_hid_status = QLabel("Chưa chọn thiết bị HID.")
        self._lbl_hid_status.setWordWrap(True)
        w_hid = QWidget()
        w_hid_l = QVBoxLayout(w_hid)
        w_hid_l.addWidget(btn_hid)
        w_hid_l.addWidget(self._lbl_hid_status)

        w_cam = QWidget()
        w_cam_l = QVBoxLayout(w_cam)
        w_cam_l.addWidget(
            QLabel(
                "Mã vạch được đọc từ camera ghi (pyzbar). "
                "Chỉnh vùng ROI trên màn Quầy sau khi hoàn tất thiết lập."
            )
        )

        self._stack = QStackedWidget()
        self._stack.addWidget(w_com)
        self._stack.addWidget(w_hid)
        self._stack.addWidget(w_cam)

        outer = QVBoxLayout(self)
        outer.addWidget(self._radio_com)
        outer.addWidget(self._radio_hid)
        outer.addWidget(self._radio_cam)
        outer.addWidget(self._stack)

    def _on_mode_id(self, bid: int) -> None:
        self._stack.setCurrentIndex(bid)
        if bid == 0:
            self._refresh_ports()

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
            self._lbl_hid_status.setText(
                f"Đã chọn VID {self._hid_vid} / PID {self._hid_pid}"
            )

    def initializePage(self) -> None:
        self._sync_mode_from_cfg()

    def _sync_mode_from_cfg(self) -> None:
        wiz = self.wizard()
        assert isinstance(wiz, SetupWizard)
        st = wiz._cfg.stations[self._col]
        self._mode_grp.blockSignals(True)
        try:
            mode_id = scanner_default_mode_id(st)
            if mode_id == 1:
                self._radio_hid.setChecked(True)
                self._hid_vid = (st.scanner_usb_vid or "").strip().upper()
                self._hid_pid = (st.scanner_usb_pid or "").strip().upper()
                self._lbl_hid_status.setText(
                    f"Đã chọn VID {self._hid_vid} / PID {self._hid_pid}"
                )
                self._stack.setCurrentIndex(1)
            elif mode_id == 0:
                self._radio_com.setChecked(True)
                self._stack.setCurrentIndex(0)
                self._refresh_ports()
            else:
                self._radio_cam.setChecked(True)
                self._hid_vid = None
                self._hid_pid = None
                self._lbl_hid_status.setText("Chưa chọn thiết bị HID.")
                self._stack.setCurrentIndex(2)
                self._refresh_ports()
        finally:
            self._mode_grp.blockSignals(False)

    def _refresh_ports(self) -> None:
        wiz = self.wizard()
        assert isinstance(wiz, SetupWizard)
        raw = list_filtered_serial_ports(try_open_ports=True)
        raw = filter_com_ports_for_wizard(raw, wiz._cfg, self._col)
        self._combo.clear()
        self._combo.addItem("(Chưa chọn — đọc mã bằng camera)", "")
        for dev, label in raw:
            self._combo.addItem(label, dev)
        want = (wiz._cfg.stations[self._col].scanner_serial_port or "").strip()
        if want:
            for i in range(self._combo.count()):
                if str(self._combo.itemData(i) or "").strip() == want:
                    self._combo.setCurrentIndex(i)
                    break
        on_com = self._stack.currentIndex() == 0
        self._qr.setVisible(on_com)

    def validatePage(self) -> bool:
        wiz = self.wizard()
        assert isinstance(wiz, SetupWizard)
        st = wiz._cfg.stations[self._col]
        if self._radio_com.isChecked():
            port = str(self._combo.currentData() or "").strip()
            if not port:
                QMessageBox.warning(
                    self,
                    "Cổng COM",
                    "Chọn cổng COM. Nếu chưa thấy thiết bị, quét QR/Barcode bên dưới để chuyển COM,"
                    " rồi bấm «Làm mới thiết bị».",
                )
                return False
            wiz._cfg.stations[self._col] = apply_scanner_choice_com(st, port=port)
        elif self._radio_hid.isChecked():
            if not self._hid_vid or not self._hid_pid:
                QMessageBox.warning(
                    self,
                    "HID",
                    "Bấm «Mở thiết lập HID POS…» và hoàn tất chọn thiết bị.",
                )
                return False
            wiz._cfg.stations[self._col] = apply_scanner_choice_hid(
                st, vid=self._hid_vid, pid=self._hid_pid
            )
        else:
            wiz._cfg.stations[self._col] = apply_scanner_choice_camera_decode(st)
        return True


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
