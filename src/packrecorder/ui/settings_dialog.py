from __future__ import annotations

from dataclasses import replace

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from packrecorder.config import AppConfig


class SettingsDialog(QDialog):
    def __init__(self, cfg: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Cài đặt")
        self._cfg = cfg
        self._root = QLineEdit(cfg.video_root)
        browse = QPushButton("Chọn…")
        browse.clicked.connect(self._browse_root)
        row = QHBoxLayout()
        row.addWidget(self._root)
        row.addWidget(browse)

        self._camera = QSpinBox()
        self._camera.setRange(0, 9)
        self._camera.setValue(cfg.camera_index)

        self._packer = QComboBox()
        self._packer.setEditable(True)
        self._packer.addItems(["Máy 1", "Máy 2"])
        self._packer.setCurrentText(cfg.packer_label)

        self._ffmpeg = QLineEdit(cfg.ffmpeg_path)
        fb = QPushButton("Chọn ffmpeg…")
        fb.clicked.connect(self._browse_ffmpeg)

        self._shutdown_on = QCheckBox("Tắt máy hẹn giờ")
        self._shutdown_on.setChecked(cfg.shutdown_enabled)
        self._shutdown_time = QLineEdit(cfg.shutdown_time_hhmm)

        self._sound_on = QCheckBox("Âm báo")
        self._sound_on.setChecked(cfg.sound_enabled)
        self._sound_mode = QComboBox()
        self._sound_mode.addItems(["speaker", "scanner_host"])
        idx = 0 if cfg.sound_mode == "speaker" else 1
        self._sound_mode.setCurrentIndex(idx)

        self._beep_short = QSpinBox()
        self._beep_short.setRange(20, 2000)
        self._beep_short.setValue(cfg.beep_short_ms)
        self._beep_gap = QSpinBox()
        self._beep_gap.setRange(10, 2000)
        self._beep_gap.setValue(cfg.beep_gap_ms)
        self._beep_long = QSpinBox()
        self._beep_long.setRange(50, 3000)
        self._beep_long.setValue(cfg.beep_long_ms)

        form = QFormLayout()
        form.addRow(QLabel("Thư mục gốc video"), row)
        form.addRow("Camera (index)", self._camera)
        form.addRow("Tên máy / người gói", self._packer)
        ff_row = QHBoxLayout()
        ff_row.addWidget(self._ffmpeg)
        ff_row.addWidget(fb)
        form.addRow("ffmpeg (tuỳ chọn)", ff_row)
        form.addRow(self._shutdown_on)
        form.addRow("Giờ tắt (HH:MM)", self._shutdown_time)
        form.addRow(self._sound_on)
        form.addRow("Chế độ âm", self._sound_mode)
        form.addRow("Bíp ngắn (ms)", self._beep_short)
        form.addRow("Khoảng cách 2 bíp (ms)", self._beep_gap)
        form.addRow("Bíp dài (ms)", self._beep_long)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    def _browse_root(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Thư mục gốc", self._root.text())
        if d:
            self._root.setText(d)

    def _browse_ffmpeg(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "ffmpeg.exe", "", "ffmpeg.exe (ffmpeg.exe)"
        )
        if path:
            self._ffmpeg.setText(path)

    def result_config(self) -> AppConfig:
        mode = "speaker" if self._sound_mode.currentIndex() == 0 else "scanner_host"
        return replace(
            self._cfg,
            video_root=self._root.text().strip(),
            camera_index=self._camera.value(),
            packer_label=self._packer.currentText().strip() or "Máy 1",
            ffmpeg_path=self._ffmpeg.text().strip(),
            shutdown_enabled=self._shutdown_on.isChecked(),
            shutdown_time_hhmm=self._shutdown_time.text().strip() or "18:00",
            sound_enabled=self._sound_on.isChecked(),
            sound_mode=mode,
            beep_short_ms=self._beep_short.value(),
            beep_gap_ms=self._beep_gap.value(),
            beep_long_ms=self._beep_long.value(),
        )
