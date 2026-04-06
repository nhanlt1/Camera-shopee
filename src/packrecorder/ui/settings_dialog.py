from __future__ import annotations

import uuid
from dataclasses import replace
from functools import partial

from PySide6.QtCore import QTimer
from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from packrecorder.config import AppConfig, MultiCameraMode, StationConfig, default_stations
from packrecorder.ui.camera_preview import CameraPreviewLabel


class SettingsDialog(QDialog):
    def __init__(self, cfg: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Cài đặt")
        self.resize(640, 780)
        self._cfg = cfg

        self._root = QLineEdit(cfg.video_root)
        browse = QPushButton("Chọn…")
        browse.clicked.connect(self._browse_root)
        row = QHBoxLayout()
        row.addWidget(self._root)
        row.addWidget(browse)

        self._mode_single = QRadioButton("Một camera (mặc định)")
        self._mode_stations = QRadioButton("Đa quầy — mỗi camera + tên + quét (tuỳ chọn 1)")
        self._mode_pip = QRadioButton("PIP — hai camera, một file (tuỳ chọn 2)")
        grp = QButtonGroup(self)
        grp.addButton(self._mode_single)
        grp.addButton(self._mode_stations)
        grp.addButton(self._mode_pip)
        if cfg.multi_camera_mode == "stations":
            self._mode_stations.setChecked(True)
        elif cfg.multi_camera_mode == "pip":
            self._mode_pip.setChecked(True)
        else:
            self._mode_single.setChecked(True)

        mode_layout = QVBoxLayout()
        mode_layout.addWidget(self._mode_single)
        mode_layout.addWidget(self._mode_stations)
        mode_layout.addWidget(self._mode_pip)
        mode_box = QGroupBox("Chế độ camera")
        mode_box.setLayout(mode_layout)

        self._stack = QStackedWidget()
        self._build_page_single(cfg)
        self._build_page_stations(cfg)
        self._build_page_pip(cfg)

        self._mode_single.toggled.connect(self._on_mode_changed)
        self._mode_stations.toggled.connect(self._on_mode_changed)
        self._mode_pip.toggled.connect(self._on_mode_changed)
        self._sync_stack()

        preview_box = QGroupBox("Xem trực tiếp (kiểm tra đúng camera)")
        preview_outer = QVBoxLayout(preview_box)
        self._preview_hint_single = QLabel(
            "Hình dưới đây là camera theo ô «Camera (index)» ở trên."
        )
        self._preview_hint_single.setWordWrap(True)
        station_prev_row = QHBoxLayout()
        station_prev_row.addWidget(QLabel("Xem camera của:"))
        self._stations_preview_combo = QComboBox()
        self._stations_preview_combo.setMinimumWidth(280)
        self._stations_preview_combo.currentIndexChanged.connect(
            self._apply_preview_from_current_ui
        )
        station_prev_row.addWidget(self._stations_preview_combo, 1)
        self._preview_station_widget = QWidget()
        self._preview_station_widget.setLayout(station_prev_row)

        pip_prev_row = QHBoxLayout()
        pip_prev_row.addWidget(QLabel("Xem trước:"))
        self._pip_preview_combo = QComboBox()
        self._pip_preview_combo.addItems(
            ["Khung chính", "Khung phụ", "Đọc mã vạch"]
        )
        self._pip_preview_combo.currentIndexChanged.connect(
            self._apply_preview_from_current_ui
        )
        pip_prev_row.addWidget(self._pip_preview_combo, 1)
        self._preview_pip_widget = QWidget()
        self._preview_pip_widget.setLayout(pip_prev_row)

        self._preview = CameraPreviewLabel(self)
        preview_outer.addWidget(self._preview_hint_single)
        preview_outer.addWidget(self._preview_station_widget)
        preview_outer.addWidget(self._preview_pip_widget)
        preview_outer.addWidget(self._preview)

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
        self._sound_mode.setCurrentIndex(0 if cfg.sound_mode == "speaker" else 1)

        self._beep_short = QSpinBox()
        self._beep_short.setRange(20, 2000)
        self._beep_short.setValue(cfg.beep_short_ms)
        self._beep_gap = QSpinBox()
        self._beep_gap.setRange(10, 2000)
        self._beep_gap.setValue(cfg.beep_gap_ms)
        self._beep_long = QSpinBox()
        self._beep_long.setRange(50, 3000)
        self._beep_long.setValue(cfg.beep_long_ms)

        common = QFormLayout()
        common.addRow(QLabel("Thư mục gốc video"), row)
        ff_row = QHBoxLayout()
        ff_row.addWidget(self._ffmpeg)
        ff_row.addWidget(fb)
        common.addRow("ffmpeg (tuỳ chọn)", ff_row)
        common.addRow(self._shutdown_on)
        common.addRow("Giờ tắt (HH:MM)", self._shutdown_time)
        common.addRow(self._sound_on)
        common.addRow("Chế độ âm", self._sound_mode)
        common.addRow("Bíp ngắn (ms)", self._beep_short)
        common.addRow("Khoảng cách 2 bíp (ms)", self._beep_gap)
        common.addRow("Bíp dài (ms)", self._beep_long)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        outer = QVBoxLayout(self)
        outer.addWidget(mode_box)
        outer.addWidget(self._stack)
        outer.addWidget(preview_box)
        outer.addLayout(common)
        outer.addWidget(buttons)

        self._sync_preview_chrome()
        self._populate_stations_preview_combo()

    def dispose_preview(self) -> None:
        self._preview.stop()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        QTimer.singleShot(0, self._apply_preview_from_current_ui)

    def _on_mode_changed(self) -> None:
        self._sync_stack()
        self._sync_preview_chrome()
        self._populate_stations_preview_combo()
        self._apply_preview_from_current_ui()

    def _sync_stack(self) -> None:
        if self._mode_single.isChecked():
            self._stack.setCurrentIndex(0)
        elif self._mode_stations.isChecked():
            self._stack.setCurrentIndex(1)
        else:
            self._stack.setCurrentIndex(2)

    def _sync_preview_chrome(self) -> None:
        self._preview_hint_single.setVisible(self._mode_single.isChecked())
        self._preview_station_widget.setVisible(self._mode_stations.isChecked())
        self._preview_pip_widget.setVisible(self._mode_pip.isChecked())

    def _preview_index_stations(self) -> int:
        data = self._stations_preview_combo.currentData()
        if not data or not self._station_rows:
            return 0
        row_i, kind = data
        if row_i < 0 or row_i >= len(self._station_rows):
            return 0
        _pk, rs, ds, _sid, _rm = self._station_rows[row_i]
        return rs.value() if kind == "rec" else ds.value()

    def _preview_index_pip(self) -> int:
        k = self._pip_preview_combo.currentIndex()
        return (
            self._pip_main.value(),
            self._pip_sub.value(),
            self._pip_decode.value(),
        )[k]

    def _apply_preview_from_current_ui(self) -> None:
        if self._mode_single.isChecked():
            self._preview.set_camera_index(self._single_camera.value())
        elif self._mode_stations.isChecked():
            self._preview.set_camera_index(self._preview_index_stations())
        elif self._mode_pip.isChecked():
            self._preview.set_camera_index(self._preview_index_pip())
        else:
            self._preview.stop()

    def _populate_stations_preview_combo(self) -> None:
        self._stations_preview_combo.blockSignals(True)
        self._stations_preview_combo.clear()
        for i, row in enumerate(self._station_rows):
            pk, rs, ds, _, _ = row
            lab = pk.text().strip() or f"Quầy {i+1}"
            self._stations_preview_combo.addItem(
                f"«{lab}» ghi → camera {rs.value()}",
                (i, "rec"),
            )
            self._stations_preview_combo.addItem(
                f"«{lab}» quét → camera {ds.value()}",
                (i, "dec"),
            )
        self._stations_preview_combo.blockSignals(False)
        if self._stations_preview_combo.count() > 0:
            self._stations_preview_combo.setCurrentIndex(0)

    def _build_page_single(self, cfg: AppConfig) -> None:
        w = QWidget()
        lay = QFormLayout(w)
        self._single_camera = QSpinBox()
        self._single_camera.setRange(0, 9)
        self._single_camera.setValue(cfg.camera_index)
        self._single_camera.valueChanged.connect(self._apply_preview_from_current_ui)
        self._single_packer = QComboBox()
        self._single_packer.setEditable(True)
        self._single_packer.addItems(["Máy 1", "Máy 2"])
        self._single_packer.setCurrentText(cfg.packer_label)
        lay.addRow("Camera (index)", self._single_camera)
        lay.addRow("Tên máy / người gói", self._single_packer)
        self._stack.addWidget(w)

    def _build_page_stations(self, cfg: AppConfig) -> None:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.addWidget(
            QLabel(
                "Mỗi dòng: nhãn gói, camera ghi, camera dùng để quét mã.\n"
                "Dùng khung «Xem trực tiếp» bên dưới để đối chiếu đúng thiết bị."
            )
        )
        self._stations_container = QWidget()
        self._stations_layout = QVBoxLayout(self._stations_container)
        self._stations_layout.setContentsMargins(0, 0, 0, 0)
        self._station_rows: list[
            tuple[QLineEdit, QSpinBox, QSpinBox, str, QPushButton]
        ] = []
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self._stations_container)
        outer.addWidget(scroll)
        add_btn = QPushButton("Thêm quầy")
        add_btn.clicked.connect(self._add_station_row)
        outer.addWidget(add_btn)
        stations = list(cfg.stations) if cfg.stations else default_stations()
        for s in stations:
            self._append_station_row(
                s.packer_label, s.record_camera_index, s.decode_camera_index, s.station_id
            )
        if not self._station_rows:
            self._add_station_row()
        self._stack.addWidget(w)

    def _append_station_row(
        self,
        packer: str,
        rec: int,
        dec: int,
        sid: str | None = None,
    ) -> None:
        sid = sid or str(uuid.uuid4())
        row_w = QWidget()
        grid = QGridLayout(row_w)
        pk = QLineEdit(packer)
        rs = QSpinBox()
        rs.setRange(0, 9)
        rs.setValue(rec)
        ds = QSpinBox()
        ds.setRange(0, 9)
        ds.setValue(dec)
        rm = QPushButton("Xóa")
        grid.addWidget(QLabel("Nhãn"), 0, 0)
        grid.addWidget(pk, 0, 1)
        grid.addWidget(QLabel("Cam ghi"), 0, 2)
        grid.addWidget(rs, 0, 3)
        grid.addWidget(QLabel("Cam quét"), 0, 4)
        grid.addWidget(ds, 0, 5)
        grid.addWidget(rm, 0, 6)

        rs.valueChanged.connect(self._apply_preview_from_current_ui)
        ds.valueChanged.connect(self._apply_preview_from_current_ui)
        rs.valueChanged.connect(
            partial(self._repopulate_stations_preview_combo_keep_index)
        )
        ds.valueChanged.connect(
            partial(self._repopulate_stations_preview_combo_keep_index)
        )

        def do_remove() -> None:
            if len(self._station_rows) <= 1:
                return
            self._station_rows[:] = [x for x in self._station_rows if x[4] is not rm]
            row_w.deleteLater()
            self._populate_stations_preview_combo()
            self._apply_preview_from_current_ui()

        rm.clicked.connect(do_remove)
        self._stations_layout.addWidget(row_w)
        self._station_rows.append((pk, rs, ds, sid, rm))

    def _repopulate_stations_preview_combo_keep_index(self, *_args: object) -> None:
        idx = self._stations_preview_combo.currentIndex()
        self._populate_stations_preview_combo()
        if 0 <= idx < self._stations_preview_combo.count():
            self._stations_preview_combo.setCurrentIndex(idx)
        self._apply_preview_from_current_ui()

    def _add_station_row(self) -> None:
        n = len(self._station_rows) + 1
        self._append_station_row(f"Máy {n}", min(9, n - 1), min(9, n - 1), None)
        self._populate_stations_preview_combo()
        self._apply_preview_from_current_ui()

    def _build_page_pip(self, cfg: AppConfig) -> None:
        w = QWidget()
        lay = QFormLayout(w)
        self._pip_main = QSpinBox()
        self._pip_main.setRange(0, 9)
        self._pip_main.setValue(cfg.pip_main_camera_index)
        self._pip_sub = QSpinBox()
        self._pip_sub.setRange(0, 9)
        self._pip_sub.setValue(cfg.pip_sub_camera_index)
        self._pip_decode = QSpinBox()
        self._pip_decode.setRange(0, 9)
        self._pip_decode.setValue(cfg.pip_decode_camera_index)
        self._pip_packer = QComboBox()
        self._pip_packer.setEditable(True)
        self._pip_packer.addItems(["Máy 1", "Máy 2"])
        self._pip_packer.setCurrentText(cfg.packer_label)
        self._pip_ow = QSpinBox()
        self._pip_ow.setRange(160, 640)
        self._pip_ow.setValue(cfg.pip_overlay_max_width)
        self._pip_mg = QSpinBox()
        self._pip_mg.setRange(4, 80)
        self._pip_mg.setValue(cfg.pip_overlay_margin)
        lay.addRow("Camera khung chính (index)", self._pip_main)
        lay.addRow("Camera khung phụ (index)", self._pip_sub)
        lay.addRow("Camera đọc mã vạch", self._pip_decode)
        lay.addRow("Tên / nhãn gói", self._pip_packer)
        lay.addRow("Độ rộng tối đa khung phụ (px)", self._pip_ow)
        lay.addRow("Lề góc (px)", self._pip_mg)
        self._pip_main.valueChanged.connect(self._apply_preview_from_current_ui)
        self._pip_sub.valueChanged.connect(self._apply_preview_from_current_ui)
        self._pip_decode.valueChanged.connect(self._apply_preview_from_current_ui)
        self._stack.addWidget(w)

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

    def _collect_stations(self) -> list[StationConfig]:
        out: list[StationConfig] = []
        for pk, rs, ds, sid, _rm in self._station_rows:
            label = pk.text().strip() or "Máy 1"
            out.append(
                StationConfig(
                    sid,
                    label,
                    rs.value(),
                    ds.value(),
                )
            )
        return out if out else default_stations()

    def result_config(self) -> AppConfig:
        multi: MultiCameraMode = "single"
        if self._mode_stations.isChecked():
            multi = "stations"
        elif self._mode_pip.isChecked():
            multi = "pip"

        sound_mode = "speaker" if self._sound_mode.currentIndex() == 0 else "scanner_host"

        base = replace(
            self._cfg,
            video_root=self._root.text().strip(),
            ffmpeg_path=self._ffmpeg.text().strip(),
            shutdown_enabled=self._shutdown_on.isChecked(),
            shutdown_time_hhmm=self._shutdown_time.text().strip() or "18:00",
            sound_enabled=self._sound_on.isChecked(),
            sound_mode=sound_mode,
            beep_short_ms=self._beep_short.value(),
            beep_gap_ms=self._beep_gap.value(),
            beep_long_ms=self._beep_long.value(),
            multi_camera_mode=multi,
            stations=self._collect_stations(),
            camera_index=self._single_camera.value(),
            packer_label=self._single_packer.currentText().strip() or "Máy 1",
            pip_main_camera_index=self._pip_main.value(),
            pip_sub_camera_index=self._pip_sub.value(),
            pip_decode_camera_index=self._pip_decode.value(),
            pip_overlay_max_width=self._pip_ow.value(),
            pip_overlay_margin=self._pip_mg.value(),
        )
        if self._mode_pip.isChecked():
            base = replace(
                base,
                packer_label=self._pip_packer.currentText().strip() or "Máy 1",
            )
        return base
