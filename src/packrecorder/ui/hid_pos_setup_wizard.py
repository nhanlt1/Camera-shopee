"""Wizard: hướng dẫn HID POS, liệt kê thiết bị, rút/cắm nhận diện, xác nhận VID/PID."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from packrecorder.hid_scanner_discovery import (
    HID_POS_USAGE_PAGE,
    diff_snapshots,
    device_label,
    enumerate_hid_or_error,
    filter_scanner_candidates,
    list_usage_page_devices,
    vid_pid_int_from_device,
)


class HidPosSetupWizard(QWizard):
    """Ba bước: hướng dẫn → chọn / rút-cắm → xác nhận."""

    vid_pid_chosen = Signal(int, int)

    PAGE_INTRO = 0
    PAGE_DISCOVER = 1
    PAGE_CONFIRM = 2

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Thiết lập máy quét HID POS")
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)

        self._all_devices: list[dict[str, Any]] = []
        self._pending_vid: int | None = None
        self._pending_pid: int | None = None
        self._snap_before_unplug: list[dict[str, Any]] | None = None
        self._snap_after_unplug: list[dict[str, Any]] | None = None

        self._page_intro = self._build_intro_page()
        self._page_discover = self._build_discover_page()
        self._page_confirm = self._build_confirm_page()

        self.addPage(self._page_intro)
        self.addPage(self._page_discover)
        self.addPage(self._page_confirm)

        self.currentIdChanged.connect(self._on_page_changed)

    def _build_intro_page(self) -> QWizardPage:
        p = QWizardPage()
        p.setTitle("Bước 1 — Chế độ HID POS")
        lay = QVBoxLayout(p)
        lay.addWidget(
            QLabel(
                "Nếu máy quét đang ở chế độ «bàn phím» (gõ vào Notepad), hãy quét mã cấu hình "
                "từ sách hướng dẫn để chuyển sang chế độ HID POS / USB-HID (tên tùy hãng).\n\n"
                "Sau đó bấm «Tiếp» để app liệt kê thiết bị và chọn đúng máy quét."
            )
        )
        lay.addStretch(1)
        return p

    def _build_discover_page(self) -> QWizardPage:
        p = QWizardPage()
        p.setTitle("Bước 2 — Chọn máy quét")
        root = QVBoxLayout(p)

        row = QHBoxLayout()
        btn_refresh = QPushButton("Làm mới danh sách")
        btn_refresh.setObjectName("hid_wizard_btn_refresh")
        btn_refresh.clicked.connect(self._refresh_device_list)
        row.addWidget(btn_refresh)
        row.addStretch(1)
        root.addLayout(row)

        self._list_devices = QListWidget()
        self._list_devices.setObjectName("hid_wizard_list_devices")
        self._list_devices.itemSelectionChanged.connect(self._on_list_selection_changed)
        root.addWidget(self._list_devices, 1)

        hint = QLabel("")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#1565c0;font-size:12px;")
        self._lbl_usage_hint = hint
        root.addWidget(hint)

        grp = QGroupBox("Rút / cắm (tuỳ chọn — khi danh sách khó phân biệt)")
        gl = QVBoxLayout(grp)
        self._btn_snap_start = QPushButton("Bắt đầu (ghi nhớ thiết bị hiện tại)")
        self._btn_snap_start.clicked.connect(self._on_unplug_snap_start)
        gl.addWidget(self._btn_snap_start)
        gl.addWidget(QLabel("1) Rút máy quét khỏi USB."))
        self._btn_unplugged = QPushButton("Đã rút")
        self._btn_unplugged.clicked.connect(self._on_unplug_done)
        self._btn_unplugged.setEnabled(False)
        gl.addWidget(self._btn_unplugged)
        gl.addWidget(QLabel("2) Cắm lại máy quét vào cùng cổng (hoặc cổng khác)."))
        self._btn_plugged = QPushButton("Đã cắm lại")
        self._btn_plugged.clicked.connect(self._on_plug_done)
        self._btn_plugged.setEnabled(False)
        gl.addWidget(self._btn_plugged)
        self._lbl_unplug_status = QLabel("")
        self._lbl_unplug_status.setWordWrap(True)
        gl.addWidget(self._lbl_unplug_status)
        root.addWidget(grp)

        return p

    def _build_confirm_page(self) -> QWizardPage:
        p = QWizardPage()
        p.setTitle("Bước 3 — Xác nhận")
        lay = QVBoxLayout(p)
        self._lbl_confirm = QLabel("")
        self._lbl_confirm.setWordWrap(True)
        lay.addWidget(self._lbl_confirm)
        lay.addStretch(1)
        return p

    def _on_page_changed(self, page_id: int) -> None:
        if page_id == self.PAGE_DISCOVER:
            self._refresh_device_list()
        elif page_id == self.PAGE_CONFIRM:
            if self._pending_vid is None or self._pending_pid is None:
                self._lbl_confirm.setText("Chưa chọn thiết bị.")
            else:
                v, p = self._pending_vid, self._pending_pid
                self._lbl_confirm.setText(
                    f"VID: {v:04X} ({v})  |  PID: {p:04X} ({p})\n\n"
                    "Bấm «Hoàn tất» để áp dụng vào cấu hình quầy."
                )

    def _refresh_device_list(self) -> None:
        self._list_devices.clear()
        raw, err = enumerate_hid_or_error()
        if err:
            QMessageBox.warning(self, "HID", err)
            self._all_devices = []
            self._lbl_usage_hint.setText("")
            return
        assert raw is not None
        self._all_devices = raw
        pos_n = len(list_usage_page_devices(raw, HID_POS_USAGE_PAGE))
        if pos_n == 0:
            self._lbl_usage_hint.setText(
                "Không thấy thiết bị HID POS (Usage Page 0x8C). "
                "Vẫn có thể chọn theo tên thiết bị nếu máy quét xuất hiện trong danh sách."
            )
        elif pos_n == 1:
            self._lbl_usage_hint.setText(
                "Phát hiện 1 thiết bị HID POS (Usage Page 0x8C). "
                "Ưu tiên chọn mục tương ứng trong danh sách (hoặc dùng rút/cắm nếu không chắc)."
            )
        else:
            self._lbl_usage_hint.setText(
                f"Phát hiện {pos_n} thiết bị HID POS (0x8C). "
                "Chọn đúng dòng trong danh sách hoặc dùng rút/cắm để xác định một máy."
            )

        candidates = filter_scanner_candidates(raw)
        for d in candidates:
            item = QListWidgetItem(device_label(d))
            item.setData(Qt.ItemDataRole.UserRole, d)
            self._list_devices.addItem(item)

    def _on_list_selection_changed(self) -> None:
        items = self._list_devices.selectedItems()
        if not items:
            self._pending_vid = None
            self._pending_pid = None
            return
        d = items[0].data(Qt.ItemDataRole.UserRole)
        if isinstance(d, dict):
            self._pending_vid, self._pending_pid = vid_pid_int_from_device(d)

    def _on_unplug_snap_start(self) -> None:
        raw, err = enumerate_hid_or_error()
        if err:
            QMessageBox.warning(self, "HID", err)
            return
        self._snap_before_unplug = list(raw) if raw else []
        self._snap_after_unplug = None
        self._btn_unplugged.setEnabled(True)
        self._btn_plugged.setEnabled(False)
        self._lbl_unplug_status.setText("Đã ghi nhớ. Rút máy quét, sau đó bấm «Đã rút».")

    def _on_unplug_done(self) -> None:
        raw, err = enumerate_hid_or_error()
        if err:
            QMessageBox.warning(self, "HID", err)
            return
        if not self._snap_before_unplug:
            self._lbl_unplug_status.setText("Chưa bấm «Bắt đầu».")
            return
        after = list(raw) if raw else []
        self._snap_after_unplug = after
        removed, _ = diff_snapshots(self._snap_before_unplug, after)
        self._btn_plugged.setEnabled(True)
        if not removed:
            self._lbl_unplug_status.setText(
                "Không thấy thiết bị nào biến mất. Thử rút đúng máy quét và bấm lại «Đã rút»."
            )
            return
        if len(removed) == 1:
            self._lbl_unplug_status.setText(
                "Đã phát hiện thiết bị vừa rút. Cắm lại rồi bấm «Đã cắm lại»."
            )
        else:
            self._lbl_unplug_status.setText(
                f"Có {len(removed)} thiết bị biến mất — sau khi cắm lại, app sẽ chọn thiết bị mới xuất hiện."
            )

    def _on_plug_done(self) -> None:
        raw, err = enumerate_hid_or_error()
        if err:
            QMessageBox.warning(self, "HID", err)
            return
        if self._snap_after_unplug is None:
            self._lbl_unplug_status.setText("Chưa có bước «Đã rút».")
            return
        after = list(raw) if raw else []
        _, added = diff_snapshots(self._snap_after_unplug, after)
        if not added:
            self._lbl_unplug_status.setText(
                "Không thấy thiết bị mới. Kiểm tra cáp USB và bấm «Đã cắm lại» lại."
            )
            return
        pick = added[0] if len(added) == 1 else added[-1]
        self._pending_vid, self._pending_pid = vid_pid_int_from_device(pick)
        label = device_label(pick)
        self._lbl_unplug_status.setText(f"Đã chọn: {label}. Bấm «Tiếp» để xác nhận.")
        self._select_list_by_vid_pid(self._pending_vid, self._pending_pid)

    def _select_list_by_vid_pid(self, vid: int, pid: int) -> None:
        for i in range(self._list_devices.count()):
            it = self._list_devices.item(i)
            d = it.data(Qt.ItemDataRole.UserRole)
            if not isinstance(d, dict):
                continue
            v, p = vid_pid_int_from_device(d)
            if v == vid and p == pid:
                self._list_devices.setCurrentItem(it)
                break

    def accept(self) -> None:
        if self._pending_vid is not None and self._pending_pid is not None:
            self.vid_pid_chosen.emit(self._pending_vid, self._pending_pid)
        super().accept()

    def validateCurrentPage(self) -> bool:
        pid = self.currentId()
        if pid == self.PAGE_DISCOVER:
            if self._pending_vid is None or self._pending_pid is None:
                QMessageBox.information(
                    self,
                    "Chọn thiết bị",
                    "Chọn một dòng trong danh sách hoặc dùng rút/cắm để gán VID/PID.",
                )
                return False
        return True
