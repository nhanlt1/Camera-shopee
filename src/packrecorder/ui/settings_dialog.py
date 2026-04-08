from __future__ import annotations

import uuid
from dataclasses import replace

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
    QMessageBox,
)

from packrecorder.config import (
    AppConfig,
    MultiCameraMode,
    StationConfig,
    default_stations,
    stations_non_serial_decode_collision,
)


class SettingsDialog(QDialog):
    def __init__(self, cfg: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Cài đặt")
        self.resize(640, 640)
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

        self._ffmpeg = QLineEdit(cfg.ffmpeg_path)
        self._ffmpeg.setPlaceholderText(
            r"Để trống nếu ffmpeg đã có trong PATH — hoặc ví dụ C:\ffmpeg\bin\ffmpeg.exe"
        )
        self._ffmpeg.setToolTip(
            "Đường dẫn đầy đủ tới ffmpeg.exe. Nếu để trống: bản build PyInstaller dùng ffmpeg.exe "
            "kèm cạnh file .exe; bản chạy Python dùng PATH hoặc thư mục thường gặp (Chocolatey, Scoop…)."
        )
        fb = QPushButton("Chọn ffmpeg…")
        fb.clicked.connect(self._browse_ffmpeg)

        self._shutdown_on = QCheckBox("Tắt máy hẹn giờ")
        self._shutdown_on.setChecked(cfg.shutdown_enabled)
        self._shutdown_on.setToolTip(
            "Đến giờ hẹn, hộp đếm ngược chỉ hiện nếu 20 phút liền không có thao tác "
            "(chuột, bàn phím, quét mã, nhập mã…)."
        )
        self._shutdown_time = QLineEdit(cfg.shutdown_time_hhmm)

        self._sound_on = QCheckBox("Âm báo")
        self._sound_on.setChecked(cfg.sound_enabled)
        self._sound_mode = QComboBox()
        self._sound_mode.addItems(["speaker", "scanner_host"])
        self._sound_mode.setCurrentIndex(0 if cfg.sound_mode == "speaker" else 1)

        self._always_top = QCheckBox(
            "Luôn hiển thị cửa sổ trên cùng (ghim — hỗ trợ máy quét kiểu bàn phím)"
        )
        self._always_top.setChecked(cfg.window_always_on_top)
        self._always_top.setToolTip(
            "Giữ cửa sổ nổi trên các app khác. Máy quét USB–COM không cần. "
            "Máy quét giả lập bàn phím: luôn dùng chế độ Đa quầy và để tiêu điểm ở ô «Mã đơn»."
        )
        self._mp_camera = QCheckBox(
            "Capture/quét mã qua multiprocessing + bộ nhớ chia sẻ (giảm nghẽn UI; Windows)"
        )
        self._mp_camera.setChecked(cfg.use_multiprocessing_camera_pipeline)
        self._mp_camera.setToolTip(
            "Đọc camera và pyzbar chạy tiến trình riêng, khung hình qua SharedMemory. "
            "Ghi FFmpeg vẫn ở tiến trình chính. Tắt nếu gặp lỗi hoặc treo khi mở camera."
        )

        self._retention = QSpinBox()
        self._retention.setRange(0, 3650)
        self._retention.setValue(int(cfg.video_retention_keep_days))
        self._retention.setToolTip(
            "Số ngày giữ thư mục quay theo YYYY-MM-DD trong thư mục gốc (và backup nếu có); "
            "0 = tắt tự xóa."
        )
        self._backup_root = QLineEdit(cfg.video_backup_root)
        self._backup_root.setPlaceholderText("Ổ dự phòng khi Drive/Primary lỗi (tuỳ chọn)")
        br_btn = QPushButton("Chọn…")
        br_btn.clicked.connect(self._browse_backup)
        backup_row = QHBoxLayout()
        backup_row.addWidget(self._backup_root)
        backup_row.addWidget(br_btn)
        self._remote_status = QLineEdit(cfg.remote_status_json_path)
        self._remote_status.setPlaceholderText(
            "Máy phụ: đường đầy đủ tới status.json (Drive map hoặc UNC)"
        )
        rs_btn = QPushButton("Chọn…")
        rs_btn.clicked.connect(self._browse_remote_status)
        rs_row = QHBoxLayout()
        rs_row.addWidget(self._remote_status)
        rs_row.addWidget(rs_btn)
        self._status_rel = QLineEdit(cfg.status_json_relative)
        self._status_rel.setPlaceholderText("PackRecorder/status.json")

        vid_box = QGroupBox("Quản lý video")
        vf = QFormLayout(vid_box)
        vf.addRow("Giữ video tối đa (ngày), sau đó xóa thư mục ngày cũ", self._retention)

        ha_box = QGroupBox("Lưu trữ dự phòng & heartbeat")
        hf = QFormLayout(ha_box)
        hf.addRow("Thư mục backup (local)", backup_row)
        hf.addRow("File status.json (máy phụ — theo dõi)", rs_row)
        hf.addRow("Đường tương đối status (máy ghi)", self._status_rel)

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
        common.addRow("Đường dẫn ffmpeg.exe (tuỳ chọn)", ff_row)
        common.addRow(self._shutdown_on)
        common.addRow("Giờ tắt (HH:MM)", self._shutdown_time)
        common.addRow(self._sound_on)
        common.addRow("Chế độ âm", self._sound_mode)
        common.addRow("Bíp ngắn (ms)", self._beep_short)
        common.addRow("Khoảng cách 2 bíp (ms)", self._beep_gap)
        common.addRow("Bíp dài (ms)", self._beep_long)
        common.addRow(self._always_top)
        common.addRow(self._mp_camera)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        outer = QVBoxLayout(self)
        outer.addWidget(mode_box)
        outer.addWidget(self._stack)
        outer.addLayout(common)
        outer.addWidget(vid_box)
        outer.addWidget(ha_box)
        outer.addWidget(buttons)

    def accept(self) -> None:
        if self._mode_stations.isChecked():
            stations = self._collect_stations()
            if stations_non_serial_decode_collision(stations):
                QMessageBox.warning(
                    self,
                    "Trùng camera đọc mã",
                    "Hai quầy đang cùng «Camera đọc mã» và không dùng máy quét COM.\n"
                    "Mã quét từ camera chỉ được gán một quầy — hãy sửa trước khi lưu.",
                )
                return
        super().accept()

    def _on_mode_changed(self) -> None:
        self._sync_stack()

    def _sync_stack(self) -> None:
        if self._mode_single.isChecked():
            self._stack.setCurrentIndex(0)
        elif self._mode_stations.isChecked():
            self._stack.setCurrentIndex(1)
        else:
            self._stack.setCurrentIndex(2)

    def _build_page_single(self, cfg: AppConfig) -> None:
        w = QWidget()
        lay = QFormLayout(w)
        self._single_camera = QSpinBox()
        self._single_camera.setRange(0, 9)
        self._single_camera.setValue(cfg.camera_index)
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
                "Mỗi dòng: nhãn gói + camera mã nguồn (xem trước chính, ghi, đọc mã khi không dùng COM)."
            )
        )
        self._stations_container = QWidget()
        self._stations_layout = QVBoxLayout(self._stations_container)
        self._stations_layout.setContentsMargins(0, 0, 0, 0)
        self._station_rows: list[tuple[QLineEdit, QSpinBox, str, QPushButton]] = []
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
                s.packer_label, s.record_camera_index, s.station_id
            )
        if not self._station_rows:
            self._add_station_row()
        self._stack.addWidget(w)

    def _append_station_row(
        self,
        packer: str,
        rec: int,
        sid: str | None = None,
    ) -> None:
        sid = sid or str(uuid.uuid4())
        row_w = QWidget()
        grid = QGridLayout(row_w)
        pk = QLineEdit(packer)
        rs = QSpinBox()
        rs.setRange(0, 9)
        rs.setValue(rec)
        rm = QPushButton("Xóa")
        grid.addWidget(QLabel("Nhãn"), 0, 0)
        grid.addWidget(pk, 0, 1)
        grid.addWidget(QLabel("Camera (mã nguồn)"), 0, 2)
        grid.addWidget(rs, 0, 3)
        grid.addWidget(rm, 0, 4)

        def do_remove() -> None:
            if len(self._station_rows) <= 1:
                return
            self._station_rows[:] = [x for x in self._station_rows if x[3] is not rm]
            row_w.deleteLater()

        rm.clicked.connect(do_remove)
        self._stations_layout.addWidget(row_w)
        self._station_rows.append((pk, rs, sid, rm))

    def _add_station_row(self) -> None:
        n = len(self._station_rows) + 1
        self._append_station_row(f"Máy {n}", min(9, n - 1), None)

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

    def _browse_backup(self) -> None:
        d = QFileDialog.getExistingDirectory(
            self, "Thư mục backup video", self._backup_root.text()
        )
        if d:
            self._backup_root.setText(d)

    def _browse_remote_status(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Chọn status.json",
            self._remote_status.text() or "",
            "JSON (*.json);;Mọi file (*.*)",
        )
        if path:
            self._remote_status.setText(path)

    def _collect_stations(self) -> list[StationConfig]:
        old_by_id = {s.station_id: s for s in self._cfg.stations}
        out: list[StationConfig] = []
        for pk, rs, sid, _rm in self._station_rows:
            label = pk.text().strip() or "Máy 1"
            prev = old_by_id.get(sid)
            cam = rs.value()
            out.append(
                StationConfig(
                    sid,
                    label,
                    cam,
                    cam,
                    scanner_serial_port=prev.scanner_serial_port if prev else "",
                    scanner_serial_baud=prev.scanner_serial_baud if prev else 9600,
                    preview_display_index=-1,
                    record_roi_norm=prev.record_roi_norm if prev else None,
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

        rel_status = self._status_rel.text().strip() or "PackRecorder/status.json"
        base = replace(
            self._cfg,
            video_root=self._root.text().strip(),
            ffmpeg_path=self._ffmpeg.text().strip(),
            window_always_on_top=self._always_top.isChecked(),
            use_multiprocessing_camera_pipeline=self._mp_camera.isChecked(),
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
            video_retention_keep_days=int(self._retention.value()),
            video_backup_root=self._backup_root.text().strip(),
            remote_status_json_path=self._remote_status.text().strip(),
            status_json_relative=rel_status,
        )
        if self._mode_pip.isChecked():
            base = replace(
                base,
                packer_label=self._pip_packer.currentText().strip() or "Máy 1",
            )
        return base
