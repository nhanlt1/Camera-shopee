from __future__ import annotations

import os
import subprocess
import sys
import uuid
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QGuiApplication, QPalette, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QFrame,
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
    WINSON_MODE_USB_COM,
    WINSON_MODE_USB_HID,
    WINSON_MODE_USB_KEYBOARD,
    AppConfig,
    MultiCameraMode,
    StationConfig,
    default_stations,
    stations_non_serial_decode_collision,
)
from packrecorder.session_log import log_session_error


class SettingsDialog(QDialog):
    def __init__(
        self,
        cfg: AppConfig,
        parent=None,
        *,
        on_test_notification: Callable[[str], None] | None = None,
        on_run_setup_wizard: Callable[[], None] | None = None,
        on_startup_shortcut_created: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Cài đặt")
        self._cfg = cfg
        self._on_test_notification = on_test_notification
        self._on_run_setup_wizard = on_run_setup_wizard
        self._on_startup_shortcut_created = on_startup_shortcut_created

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

        self._kiosk_hide_form = QCheckBox(
            "Ẩn form thiết bị trên Quầy (chế độ hằng ngày)"
        )
        self._kiosk_hide_form.setChecked(cfg.default_to_kiosk)
        self._kiosk_hide_form.setToolTip(
            "Khi bật và đã hoàn tất thiết lập: chỉ thấy preview + trạng thái; "
            "chi tiết thiết bị trong Wizard hoặc Cài đặt. Tắt để luôn thấy form chỉnh thiết bị trên Quầy."
        )
        self._kiosk_fullscreen = QCheckBox(
            "Toàn màn hình khi khởi động (sau thiết lập)"
        )
        self._kiosk_fullscreen.setChecked(cfg.kiosk_fullscreen_on_start)
        self._kiosk_fullscreen.setToolTip(
            "Áp dụng khi chế độ Đa quầy và đã hoàn tất thiết lập lần đầu."
        )
        kiosk_layout = QVBoxLayout()
        kiosk_layout.addWidget(self._kiosk_hide_form)
        kiosk_layout.addWidget(self._kiosk_fullscreen)
        kiosk_box = QGroupBox("Quầy hằng ngày (đa quầy)")
        kiosk_box.setLayout(kiosk_layout)

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
            "(chuột, quét mã, nhập mã…)."
        )
        self._shutdown_time = QLineEdit(cfg.shutdown_time_hhmm)

        self._sound_on = QCheckBox("Âm báo")
        self._sound_on.setChecked(cfg.sound_enabled)
        self._sound_mode = QComboBox()
        self._sound_mode.addItems(["speaker", "scanner_host"])
        self._sound_mode.setCurrentIndex(0 if cfg.sound_mode == "speaker" else 1)

        self._always_top = QCheckBox("Luôn hiển thị cửa sổ trên cùng (ghim)")
        self._always_top.setChecked(cfg.window_always_on_top)
        self._always_top.setToolTip("Giữ cửa sổ nổi trên các app khác.")
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
        self._status_json_hint = QLabel(
            "File trạng thái (heartbeat) luôn nằm cùng thư mục gốc video "
            "(…\\PackRecorder\\status.json). Máy phụ chỉ cần trỏ «Thư mục gốc video» tới cùng ổ/thư mục đã đồng bộ."
        )
        self._status_json_hint.setWordWrap(True)

        vid_box = QGroupBox("Quản lý video")
        vf = QFormLayout(vid_box)
        vf.addRow("Giữ video tối đa (ngày), sau đó xóa thư mục ngày cũ", self._retention)

        ha_box = QGroupBox("Ổ dự phòng và trạng thái máy")
        ha_box.setToolTip(
            "Ổ dự phòng: lưu video khi ổ chính (ví dụ Drive) lỗi. "
            "Heartbeat ghi tự động dưới thư mục gốc video (PackRecorder/status.json)."
        )
        hf = QFormLayout(ha_box)
        hf.addRow("Thư mục dự phòng (máy quay)", backup_row)
        hf.addRow(self._status_json_hint)

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
        test_outer = QWidget()
        test_row = QHBoxLayout(test_outer)
        test_row.setContentsMargins(0, 0, 0, 0)
        self._test_notify_source = QComboBox()
        self._test_notify_source.addItem("Loa / beep hệ thống", "speaker")
        self._test_notify_source.addItem("Máy quét host (HID)", "scanner_host")
        self._test_notify_source.addItem("Thông báo khay", "tray")
        btn_test_notify = QPushButton("Thử thông báo")
        btn_test_notify.setToolTip(
            "Kiểm tra nguồn phát — không cần bấm Lưu; dùng cấu hình Âm báo hiện tại."
        )
        btn_test_notify.clicked.connect(self._emit_test_notification)
        test_row.addWidget(QLabel("Thử phát từ:"))
        test_row.addWidget(self._test_notify_source, 1)
        test_row.addWidget(btn_test_notify)
        if on_test_notification is None:
            self._test_notify_source.setEnabled(False)
            btn_test_notify.setEnabled(False)
        common.addRow("Thử thông báo", test_outer)
        common.addRow("Bíp ngắn (ms)", self._beep_short)
        common.addRow("Khoảng cách 2 bíp (ms)", self._beep_gap)
        common.addRow("Bíp dài (ms)", self._beep_long)
        common.addRow(self._always_top)

        self._minimize_tray = QCheckBox(
            "Thu vào khay hệ thống (đóng cửa sổ = ẩn, không thoát app)"
        )
        self._minimize_tray.setChecked(cfg.minimize_to_tray)
        self._minimize_tray.setToolTip(
            "Bật thì nút X chỉ ẩn cửa sổ; thoát thật qua menu chuột phải icon khay → Thoát."
        )
        self._start_tray = QCheckBox("Khởi động chỉ hiện icon khay (ẩn cửa sổ)")
        self._start_tray.setChecked(cfg.start_in_tray)
        self._close_tray = QCheckBox("Nút X chỉ ẩn (không dừng quay/đồng bộ)")
        self._close_tray.setChecked(cfg.close_to_tray)
        self._low_priority = QCheckBox("Ưu tiên CPU thấp (Below normal — Windows: cài pip install psutil)")
        self._low_priority.setChecked(cfg.low_process_priority)
        self._tray_toast = QCheckBox("Thông báo khay khi bắt đầu quay đơn (khi cửa sổ đang ẩn)")
        self._tray_toast.setChecked(cfg.tray_show_toast_on_order)
        self._health_interval = QSpinBox()
        self._health_interval.setRange(0, 1440)
        self._health_interval.setValue(int(cfg.tray_health_beep_interval_min))
        self._health_interval.setToolTip(
            "0 = tắt. Định kỳ phát tiếng rất nhẹ khi cửa sổ ẩn để biết app còn chạy (kho yên: chỉnh âm lượng nhỏ)."
        )
        self._health_vol = QDoubleSpinBox()
        self._health_vol.setRange(0.0, 1.0)
        self._health_vol.setSingleStep(0.05)
        self._health_vol.setDecimals(2)
        self._health_vol.setValue(float(cfg.tray_health_beep_volume))
        tray_box = QGroupBox("Khay hệ thống / chạy nền")
        tf = QFormLayout(tray_box)
        _tray_vidpid_note = QLabel(
            "Chọn VID/PID ở màn hình quầy chỉ cấu hình máy quét HID POS (đọc raw qua hidapi). "
            "Để ẩn cửa sổ và chỉ thấy icon khay, bật các tùy chọn bên dưới — hai việc không thay thế nhau. "
            "HID POS raw: app vẫn nhận mã khi cửa sổ ẩn."
        )
        _tray_vidpid_note.setWordWrap(True)
        _tray_vidpid_note.setStyleSheet("color:#555;font-size:smaller;")
        tf.addRow(_tray_vidpid_note)
        tf.addRow(self._minimize_tray)
        tf.addRow(self._start_tray)
        tf.addRow(self._close_tray)
        tf.addRow(self._low_priority)
        tf.addRow(self._tray_toast)
        tf.addRow("Bíp «còn sống» mỗi (phút), 0 = tắt", self._health_interval)
        tf.addRow("Âm lượng bíp (0–1)", self._health_vol)

        mini_box = QGroupBox("Mini-Overlay (hai quầy khi thu nhỏ / ẩn cửa sổ)")
        mini_box.setToolTip(
            "Khung trạng thái nhỏ góc màn hình khi cửa sổ chính không hiện — không dừng ghi."
        )
        mf = QFormLayout(mini_box)
        self._mini_overlay_on = QCheckBox("Bật overlay hai quầy khi thu nhỏ / ẩn cửa sổ")
        self._mini_overlay_on.setChecked(cfg.mini_overlay_enabled)
        self._mini_ct = QCheckBox("Click-through — chuột đi xuyên qua overlay")
        self._mini_ct.setChecked(cfg.mini_overlay_click_through)
        self._mini_ct.setToolTip(
            "Bật thì không bấm được lên khung overlay; dùng khi cần thao tác app phía sau."
        )
        self._mini_ct.clicked.connect(self._on_mini_overlay_click_through_clicked)
        _mini_warn = QLabel(
            "Click-through: không tương tác được với overlay — chỉ bật khi thật sự cần."
        )
        _mini_warn.setWordWrap(True)
        _mini_warn.setStyleSheet("color:#555;font-size:smaller;")
        self._mini_corner = QComboBox()
        for val, label in (
            ("bottom_right", "Dưới phải"),
            ("bottom_left", "Dưới trái"),
            ("top_right", "Trên phải"),
            ("top_left", "Trên trái"),
        ):
            self._mini_corner.addItem(label, val)
        _ix_corner = self._mini_corner.findData(cfg.mini_overlay_corner)
        self._mini_corner.setCurrentIndex(max(0, _ix_corner))

        mf.addRow(self._mini_overlay_on)
        mf.addRow(self._mini_ct)
        mf.addRow("Vị trí overlay", self._mini_corner)
        mf.addRow(_mini_warn)

        _repo_root = Path(__file__).resolve().parents[3]
        winson_box = QGroupBox("Máy quét Winson — mã cấu hình (quét vào thiết bị)")
        winson_layout = QVBoxLayout(winson_box)
        self._winson_r_com = QRadioButton("USB COM (khuyến nghị — đọc qua pyserial)")
        self._winson_r_hid = QRadioButton("USB HID (HID POS trong app)")
        self._winson_r_kb = QRadioButton("USB Keyboard (wedge bàn phím)")
        self._winson_r_com.setChecked(True)
        winson_grp = QButtonGroup(self)
        winson_grp.addButton(self._winson_r_com, 0)
        winson_grp.addButton(self._winson_r_hid, 1)
        winson_grp.addButton(self._winson_r_kb, 2)
        winson_grp.idClicked.connect(self._refresh_winson_qr_display)
        winson_layout.addWidget(self._winson_r_com)
        winson_layout.addWidget(self._winson_r_hid)
        winson_layout.addWidget(self._winson_r_kb)
        self._winson_pix = QLabel()
        self._winson_pix.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._winson_str = QLabel()
        self._winson_str.setWordWrap(True)
        self._winson_str.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        winson_layout.addWidget(self._winson_pix)
        winson_layout.addWidget(self._winson_str)
        self._winson_paths = (
            _repo_root
            / "docs"
            / "scanner-config-codes"
            / "winson-mode-barcodes"
            / "qr-usb-com.png",
            _repo_root
            / "docs"
            / "scanner-config-codes"
            / "winson-mode-barcodes"
            / "qr-usb-hid.png",
            _repo_root
            / "docs"
            / "scanner-config-codes"
            / "winson-mode-barcodes"
            / "qr-usb-keyboard.png",
        )
        self._winson_codes = (
            WINSON_MODE_USB_COM,
            WINSON_MODE_USB_HID,
            WINSON_MODE_USB_KEYBOARD,
        )
        self._refresh_winson_qr_display(0)

        btn_wizard = QPushButton("Mở trình hướng dẫn thiết lập quầy…")
        btn_wizard.setToolTip(
            "Đóng Cài đặt và mở Wizard từng bước (camera, máy quét, tên quầy)."
        )
        btn_wizard.clicked.connect(self._emit_run_setup_wizard)

        btn_startup = QPushButton("Tạo lối tắt trong thư mục Khởi động Windows…")
        btn_startup.setToolTip(
            "Tạo file .lnk trong shell:Startup — không ghi Registry. "
            "Cần quyền ghi thư mục Startup của user."
        )
        btn_startup.clicked.connect(self._create_windows_startup_shortcut)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        scroll_inner = QWidget()
        scroll_layout = QVBoxLayout(scroll_inner)
        scroll_layout.setContentsMargins(0, 0, 0, 0)
        scroll_layout.setSpacing(8)
        scroll_layout.addWidget(mode_box)
        scroll_layout.addWidget(kiosk_box)
        scroll_layout.addWidget(self._stack)
        scroll_layout.addLayout(common)
        scroll_layout.addWidget(vid_box)
        scroll_layout.addWidget(ha_box)
        scroll_layout.addWidget(winson_box)
        scroll_layout.addWidget(mini_box)
        scroll_layout.addWidget(tray_box)

        scroll = QScrollArea()
        scroll.setWidget(scroll_inner)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )
        scroll_inner.setObjectName("settingsScrollInner")
        vp = scroll.viewport()
        pal = QPalette(vp.palette())
        c = QColor("#ffffff")
        pal.setColor(QPalette.ColorRole.Base, c)
        pal.setColor(QPalette.ColorRole.Window, c)
        vp.setPalette(pal)
        vp.setAutoFillBackground(True)
        pal_inner = QPalette(scroll_inner.palette())
        pal_inner.setColor(QPalette.ColorRole.Window, c)
        scroll_inner.setPalette(pal_inner)
        scroll_inner.setAutoFillBackground(True)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        outer.setSpacing(0)
        outer.addWidget(scroll, 1)
        outer.addWidget(btn_wizard)
        outer.addWidget(btn_startup)
        outer.addWidget(buttons)

        screen = QGuiApplication.primaryScreen()
        if screen is not None:
            mh = int(screen.availableGeometry().height() * 0.88)
            self.setMaximumHeight(max(480, min(mh, 920)))
        self.resize(640, min(620, self.maximumHeight()))

    def _create_windows_startup_shortcut(self) -> None:
        target = Path(sys.executable)
        startup = (
            Path(os.environ.get("APPDATA", ""))
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / "Startup"
        )
        startup.mkdir(parents=True, exist_ok=True)
        lnk = startup / "Pack Recorder.lnk"
        work_dir = str(target.parent.resolve())
        ps = (
            f'$s=(New-Object -ComObject WScript.Shell).CreateShortcut({str(lnk)!r});'
            f'$s.TargetPath={str(target.resolve())!r};'
            f'$s.WorkingDirectory={work_dir!r};'
            f'$s.Save()'
        )
        try:
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    ps,
                ],
                check=True,
            )
        except (OSError, subprocess.CalledProcessError) as e:
            QMessageBox.warning(
                self,
                "Không tạo được lối tắt",
                f"Chi tiết: {e}",
            )
            return
        msg = f"Đã ghi:\n{lnk}"
        if not self._cfg.windows_startup_hint_shown:
            msg += (
                "\n\nLần sau đăng nhập Windows, Pack Recorder có thể chạy tự động "
                "từ thư mục Khởi động."
            )
        QMessageBox.information(
            self,
            "Đã tạo lối tắt",
            msg,
        )
        if self._on_startup_shortcut_created is not None:
            self._on_startup_shortcut_created()

    def _emit_run_setup_wizard(self) -> None:
        cb = self._on_run_setup_wizard
        self.reject()
        if cb is not None:
            cb()

    def _refresh_winson_qr_display(self, _id: int = 0) -> None:
        idx = 0
        if self._winson_r_hid.isChecked():
            idx = 1
        elif self._winson_r_kb.isChecked():
            idx = 2
        path = self._winson_paths[idx]
        pix = QPixmap(str(path))
        if not pix.isNull():
            self._winson_pix.setPixmap(
                pix.scaled(
                    180,
                    180,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        self._winson_str.setText(
            "Quét mã sau bằng máy Winson, rồi «Làm mới thiết bị» trên quầy:\n"
            f"{self._winson_codes[idx]}"
        )

    def _on_mini_overlay_click_through_clicked(self) -> None:
        if not self._mini_ct.isChecked():
            return
        QMessageBox.information(
            self,
            "Click-through",
            "Khi bật, chuột đi xuyên qua overlay — bạn không bấm được lên khung trạng thái hai quầy. "
            "Chỉ bật khi cần thao tác cửa sổ phía sau.",
        )

    def _emit_test_notification(self) -> None:
        if self._on_test_notification is None:
            return
        data = self._test_notify_source.currentData()
        if data is None:
            return
        try:
            self._on_test_notification(str(data))
        except Exception:
            log_session_error(
                "Lỗi callback «Thử thông báo» (Cài đặt).",
                exc_info=sys.exc_info(),
            )

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
        # Tránh dùng tên biến `w` cho vòng for — nếu không, `w` trỏ nhầm tới widget con
        # → trang QVBoxLayout bị GC, layout C++ «already deleted» khi mở hộp thoại.
        page = QWidget()
        outer = QVBoxLayout(page)
        outer.addWidget(
            QLabel(
                "Mỗi dòng: nhãn gói + camera mã nguồn (xem trước chính, ghi, đọc mã khi không dùng COM)."
            )
        )
        self._stations_container = QWidget()
        self._stations_layout = QVBoxLayout(self._stations_container)
        self._stations_layout.setContentsMargins(0, 0, 0, 0)
        self._station_rows: list[tuple[QLineEdit, QSpinBox, str, QPushButton]] = []
        st_scroll = QScrollArea()
        st_scroll.setWidgetResizable(True)
        st_scroll.setWidget(self._stations_container)
        st_scroll.setFrameShape(QFrame.Shape.NoFrame)
        _white = QColor("#ffffff")
        for pw in (st_scroll.viewport(), self._stations_container):
            p = QPalette(pw.palette())
            p.setColor(QPalette.ColorRole.Base, _white)
            p.setColor(QPalette.ColorRole.Window, _white)
            pw.setPalette(p)
            pw.setAutoFillBackground(True)
        outer.addWidget(st_scroll)
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
        self._stack.addWidget(page)

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
                    scanner_usb_vid=prev.scanner_usb_vid if prev else "",
                    scanner_usb_pid=prev.scanner_usb_pid if prev else "",
                    scanner_input_kind=getattr(
                        prev, "scanner_input_kind", "com"
                    )
                    if prev
                    else "com",
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

        vr = self._root.text().strip()
        rel_status = "PackRecorder/status.json"
        remote_status = str(Path(vr) / rel_status) if vr else ""
        min_tray = self._minimize_tray.isChecked()
        base = replace(
            self._cfg,
            video_root=vr,
            ffmpeg_path=self._ffmpeg.text().strip(),
            window_always_on_top=self._always_top.isChecked(),
            use_multiprocessing_camera_pipeline=True,
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
            remote_status_json_path=remote_status,
            status_json_relative=rel_status,
            minimize_to_tray=min_tray,
            start_in_tray=self._start_tray.isChecked() if min_tray else False,
            close_to_tray=self._close_tray.isChecked(),
            low_process_priority=self._low_priority.isChecked(),
            tray_show_toast_on_order=self._tray_toast.isChecked(),
            tray_health_beep_interval_min=int(self._health_interval.value()),
            tray_health_beep_volume=float(self._health_vol.value()),
            mini_overlay_enabled=self._mini_overlay_on.isChecked(),
            mini_overlay_click_through=self._mini_ct.isChecked(),
            mini_overlay_corner=str(self._mini_corner.currentData() or "bottom_right"),
            default_to_kiosk=self._kiosk_hide_form.isChecked(),
            kiosk_fullscreen_on_start=self._kiosk_fullscreen.isChecked(),
            enable_global_barcode_hook=False,
        )
        if self._mode_pip.isChecked():
            base = replace(
                base,
                packer_label=self._pip_packer.currentText().strip() or "Máy 1",
            )
        return base
