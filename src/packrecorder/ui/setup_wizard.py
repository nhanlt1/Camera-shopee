from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QMessageBox,
    QVBoxLayout,
)

from packrecorder.config import AppConfig, ensure_dual_stations, normalize_config
from packrecorder.ui.dual_station_widget import DualStationWidget


class SetupWizardDialog(QDialog):
    """Thiết lập quầy: tái sử dụng form hai cột (spec 12 — gói hướng dẫn)."""

    def __init__(self, cfg: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Thiết lập máy & quầy")
        self.resize(1000, 700)
        self._cfg = normalize_config(cfg)
        ensure_dual_stations(self._cfg)

        lay = QVBoxLayout(self)
        hint = QLabel(
            "Cấu hình camera và máy quét cho từng quầy, rồi bấm Hoàn tất. "
            "Sau đó có thể dùng màn Quầy tối giản — chi tiết nâng cao vẫn ở Tệp → Cài đặt."
        )
        hint.setWordWrap(True)
        lay.addWidget(hint)

        self._dual = DualStationWidget(kiosk_mode=False, parent=self)
        self._dual.sync_from_config(self._cfg)
        lay.addWidget(self._dual, 1)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self._on_accept)
        bb.rejected.connect(self.reject)
        ok = bb.button(QDialogButtonBox.StandardButton.Ok)
        if ok is not None:
            ok.setText("Hoàn tất")
        lay.addWidget(bb)

    def _on_accept(self) -> None:
        self._dual.apply_to_config(self._cfg)
        self._cfg = normalize_config(self._cfg)
        self._cfg.onboarding_complete = True
        self._cfg.first_run_setup_required = False
        if self._dual.duplicate_scanner_ports():
            QMessageBox.warning(
                self,
                "Trùng cổng máy quét",
                "Hai quầy đang chọn cùng một cổng/HID — chỉnh lại trước khi hoàn tất.",
            )
            return
        if self._dual.has_decode_on_peer_record_collision():
            QMessageBox.warning(
                self,
                "Xung đột camera đọc mã",
                "Điều chỉnh camera đọc mã để không trùng camera ghi của quầy kia.",
            )
            return
        self.accept()

    def result_config(self) -> AppConfig:
        return normalize_config(self._cfg)
