from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from packrecorder.camera_probe import probe_opencv_camera_indices
from packrecorder.config import AppConfig, ensure_dual_stations, normalize_config
from packrecorder.serial_ports import list_filtered_serial_ports
from packrecorder.ui.dual_station_widget import DualStationWidget, _merge_probe_with_config
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
        self._combo = QComboBox()
        form = QFormLayout()
        form.addRow("Camera ghi (USB index):", self._combo)
        outer = QVBoxLayout(self)
        outer.addLayout(form)

    def initializePage(self) -> None:
        wiz = self.wizard()
        assert isinstance(wiz, SetupWizard)
        cfg = wiz._cfg
        probed = probe_opencv_camera_indices(max_index=6, require_frame=False)
        indices = _merge_probe_with_config(probed, cfg)
        self._combo.clear()
        for i in indices:
            self._combo.addItem(f"Camera {i}", i)
        st = cfg.stations[self._col]
        want = int(st.record_camera_index) if st.record_camera_kind == "usb" else 0
        idx = self._combo.findData(want)
        if idx >= 0:
            self._combo.setCurrentIndex(idx)
        elif self._combo.count() > 0:
            self._combo.setCurrentIndex(0)

    def validatePage(self) -> bool:
        wiz = self.wizard()
        assert isinstance(wiz, SetupWizard)
        rd = self._combo.currentData()
        rec = int(rd) if rd is not None else 0
        st = wiz._cfg.stations[self._col]
        wiz._cfg.stations[self._col] = replace(
            st,
            record_camera_index=rec,
            decode_camera_index=rec,
            record_camera_kind="usb",
            record_rtsp_url="",
        )
        return True


class WizardScannerPage(QWizardPage):
    def __init__(self, col: int, parent: QWizard) -> None:
        super().__init__(parent)
        self._col = col
        self.setTitle(f"Máy {col + 1} — Máy quét (COM)")
        self._combo = QComboBox()
        self._combo.setMinimumWidth(320)
        btn = QPushButton("Làm mới thiết bị")
        btn.clicked.connect(self._refresh_ports)
        self._qr = WinsonComQrPanel(_repo_root(), self)
        self._qr.set_on_refresh(self._refresh_ports)
        form = QFormLayout()
        form.addRow("Cổng COM:", self._combo)
        form.addRow(btn)
        outer = QVBoxLayout(self)
        outer.addLayout(form)
        outer.addWidget(self._qr)

    def initializePage(self) -> None:
        self._refresh_ports()

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
        self._qr.setVisible(len(raw) == 0)

    def validatePage(self) -> bool:
        wiz = self.wizard()
        assert isinstance(wiz, SetupWizard)
        port = str(self._combo.currentData() or "").strip()
        st = wiz._cfg.stations[self._col]
        wiz._cfg.stations[self._col] = replace(
            st,
            scanner_serial_port=port,
            scanner_input_kind="com",
        )
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
