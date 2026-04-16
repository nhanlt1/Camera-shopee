from __future__ import annotations

from dataclasses import replace
from pathlib import Path

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
from packrecorder.ui.hid_pos_setup_wizard import HidPosSetupWizard
from packrecorder.ui.setup_wizard_scanner import (
    apply_scanner_choice_camera_decode,
    apply_scanner_choice_com,
    apply_scanner_choice_hid,
)
from packrecorder.ui.winson_com_qr_panel import WinsonComQrPanel


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


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
        rtsp_form = QFormLayout()
        rtsp_form.addRow("URL RTSP:", self._rtsp_url)
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
        outer.addWidget(hint)

    def _on_cam_kind_clicked(self, _bid: int) -> None:
        self._stack.setCurrentIndex(1 if self._radio_rtsp.isChecked() else 0)

    def _refill_usb_camera_combo(self, preferred_index: int | None) -> None:
        wiz = self.wizard()
        assert isinstance(wiz, SetupWizard)
        cfg = wiz._cfg
        probed = probe_opencv_camera_indices(max_index=6, require_frame=False)
        indices = _merge_probe_with_config(probed, cfg)
        self._combo.clear()
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
            if st.scanner_input_kind == "hid_pos" and (st.scanner_usb_vid or "").strip():
                self._radio_hid.setChecked(True)
                self._hid_vid = (st.scanner_usb_vid or "").strip().upper()
                self._hid_pid = (st.scanner_usb_pid or "").strip().upper()
                self._lbl_hid_status.setText(
                    f"Đã chọn VID {self._hid_vid} / PID {self._hid_pid}"
                )
                self._stack.setCurrentIndex(1)
            elif (st.scanner_serial_port or "").strip():
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
        self._qr.setVisible(on_com and len(raw) == 0)

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
                    "Chọn cổng COM hoặc chọn «Đọc mã bằng camera».",
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
