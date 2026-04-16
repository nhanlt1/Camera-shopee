from __future__ import annotations

import shutil
from datetime import datetime
from functools import partial
from pathlib import Path

from PySide6.QtCore import QDate, QSize, Qt, QUrl
from PySide6.QtGui import (
    QBrush,
    QColor,
    QDesktopServices,
    QFont,
    QIcon,
    QPainter,
    QPalette,
    QPen,
    QPixmap,
    QShowEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QDateEdit,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from packrecorder.config import AppConfig
from packrecorder.recording_index import RecordingIndex, recordings_db_path_for_search

# Cửa sổ 16 ngày gần nhất (kể cả hôm nay): today-15 … today
_DATE_RANGE_DAYS = 16


class _DateRangeDialog(QDialog):
    """Một hộp thoại: hai ô ngày có lịch popup (không nằm trên hàng lọc chính)."""

    def __init__(
        self,
        parent,
        d_from: QDate,
        d_to: QDate,
        min_d: QDate,
        max_d: QDate,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Chọn khoảng ngày")
        self._result_from = d_from
        self._result_to = d_to

        hint = QLabel(
            f"Chỉ có thể chọn trong {_DATE_RANGE_DAYS} ngày gần nhất (tính đến hôm nay)."
        )
        hint.setWordWrap(True)

        self._f = QDateEdit()
        self._f.setCalendarPopup(True)
        self._f.setDisplayFormat("dd/MM/yyyy")
        self._f.setMinimumDate(min_d)
        self._f.setMaximumDate(max_d)
        self._f.setDate(d_from)

        self._t = QDateEdit()
        self._t.setCalendarPopup(True)
        self._t.setDisplayFormat("dd/MM/yyyy")
        self._t.setMinimumDate(min_d)
        self._t.setMaximumDate(max_d)
        self._t.setDate(d_to)

        form = QFormLayout()
        form.addRow("Từ ngày", self._f)
        form.addRow("Đến ngày", self._t)

        bb = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addWidget(hint)
        lay.addLayout(form)
        lay.addWidget(bb)

    def accept(self) -> None:
        a = self._f.date()
        b = self._t.date()
        if a > b:
            a, b = b, a
        self._result_from = a
        self._result_to = b
        super().accept()

    def result_from(self) -> QDate:
        return self._result_from

    def result_to(self) -> QDate:
        return self._result_to


def _format_created_at_display(raw: str) -> str:
    t = (raw or "").strip()
    if not t:
        return ""
    try:
        if t.endswith("Z"):
            t = t[:-1] + "+00:00"
        dt = datetime.fromisoformat(t)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return f"{dt.day:02d}/{dt.month:02d}/{dt.year}  {dt.hour:02d}:{dt.minute:02d}"
    except ValueError:
        return t


def _item_optional_text(text: str) -> QTableWidgetItem:
    s = (text or "").strip()
    if not s:
        it = QTableWidgetItem("—")
        it.setForeground(QBrush(QColor("#9e9e9e")))
        return it
    return QTableWidgetItem(s)


def _item_time_display(raw: str) -> QTableWidgetItem:
    s = (raw or "").strip()
    if not s:
        it = QTableWidgetItem("—")
        it.setForeground(QBrush(QColor("#9e9e9e")))
        return it
    it = QTableWidgetItem(_format_created_at_display(raw))
    it.setToolTip(raw)
    it.setFont(QFont("Segoe UI", 9))
    it.setForeground(QBrush(QColor("#37474f")))
    return it


def _green_check_icon(size: int = 18) -> QIcon:
    pm = QPixmap(size, size)
    pm.fill(QColor(0, 0, 0, 0))
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    pen = QPen(QColor("#2e7d32"))
    pen.setWidthF(2.25)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    p.setPen(pen)
    p.drawLine(4, int(size * 0.52), int(size * 0.42), int(size * 0.72))
    p.drawLine(int(size * 0.42), int(size * 0.72), int(size * 0.78), int(size * 0.28))
    p.end()
    return QIcon(pm)


def _item_storage_status(raw_st: str) -> QTableWidgetItem:
    app = QApplication.instance()
    style = app.style() if app is not None else None
    if raw_st == "synced":
        it = QTableWidgetItem("Drive")
        it.setIcon(_green_check_icon())
        it.setForeground(QBrush(QColor("#2e7d32")))
        return it
    it = QTableWidgetItem("Trên máy")
    if style is not None:
        it.setIcon(style.standardIcon(QStyle.StandardPixmap.SP_DriveHDIcon))
    it.setForeground(QBrush(QColor("#424242")))
    return it


def _format_duration_hhmmss(seconds: float) -> str:
    try:
        s = max(0, int(round(float(seconds))))
    except (TypeError, ValueError):
        return "—"
    h = s // 3600
    m = (s % 3600) // 60
    ss = s % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{ss:02d}"
    return f"{m:02d}:{ss:02d}"


def _item_duration(raw_seconds: object) -> QTableWidgetItem:
    txt = _format_duration_hhmmss(float(raw_seconds or 0.0))
    it = QTableWidgetItem(txt)
    if txt == "—":
        it.setForeground(QBrush(QColor("#9e9e9e")))
    else:
        it.setForeground(QBrush(QColor("#37474f")))
    return it


def _resolve_video_path(row: dict) -> Path | None:
    rp = row.get("resolved_path") or ""
    p = Path(rp)
    if p.is_file():
        return p
    pr = (row.get("primary_root") or "").strip()
    rk = (row.get("rel_key") or "").strip()
    if pr and rk:
        cand = Path(pr).joinpath(*rk.replace("\\", "/").split("/"))
        if cand.is_file():
            return cand
    return None


class RecordingSearchPanel(QWidget):
    def __init__(
        self,
        cfg: AppConfig,
        *,
        office_search_stale: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._last_rows: list[dict] = []

        _ = office_search_stale  # API giữ tương thích; không còn popup «dữ liệu trễ»

        self._q = QLineEdit()
        self._q.setPlaceholderText("Mã đơn, tên người gói…")

        today = QDate.currentDate()
        min_d = today.addDays(-(_DATE_RANGE_DAYS - 1))
        self._date_from = QDate(min_d)
        self._date_to = QDate(today)

        self._btn_date_range = QPushButton()
        self._btn_date_range.setToolTip(
            f"Bấm để chọn khoảng ngày (tối đa {_DATE_RANGE_DAYS} ngày gần nhất)."
        )
        self._btn_date_range.clicked.connect(self._open_date_range)
        self._update_date_range_button_text()

        self._btn_all = QPushButton("Tất cả")
        self._btn_drive = QPushButton("Drive")
        self._btn_local = QPushButton("Trên máy")
        self._btn_all.setToolTip("Mọi trạng thái lưu trữ")
        self._btn_drive.setToolTip("Đã đồng bộ lên ổ chính (Drive)")
        self._btn_local.setToolTip(
            "Đang chờ đẩy lên ổ chính hoặc chỉ lưu trên máy / ổ dự phòng"
        )
        for b in (self._btn_all, self._btn_drive, self._btn_local):
            b.setCheckable(True)
        self._btn_all.setChecked(True)
        self._status_group = QButtonGroup(self)
        self._status_group.setExclusive(True)
        self._status_group.addButton(self._btn_all, 0)
        self._status_group.addButton(self._btn_drive, 1)
        self._status_group.addButton(self._btn_local, 2)
        self._status_group.buttonClicked.connect(lambda _b: self._run_search())

        self._table = QTableWidget(0, 7)
        self._table.setAlternatingRowColors(True)
        self._table.setHorizontalHeaderLabels(
            [
                "Mã đơn",
                "Người gói",
                "Thời gian",
                "Thời lượng",
                "Trạng thái",
                "File video",
                "Thao tác",
            ]
        )
        hdr = self._table.horizontalHeader()
        hdr.setStretchLastSection(False)
        for col in range(5):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        vh = self._table.verticalHeader()
        vh.setAutoFillBackground(True)
        _vh_bg = QColor("#f5f5f5")
        vh_pal = vh.palette()
        vh_pal.setColor(QPalette.ColorRole.Window, _vh_bg)
        vh_pal.setColor(QPalette.ColorRole.Base, _vh_bg)
        vh_pal.setColor(QPalette.ColorRole.Button, _vh_bg)
        vh.setPalette(vh_pal)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.doubleClicked.connect(self._on_double_click)

        search_btn = QPushButton("Tìm")
        search_btn.setDefault(True)
        search_btn.clicked.connect(self._run_search)
        row = QHBoxLayout()
        row.addWidget(self._q)
        row.addWidget(search_btn)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Thời gian:"))
        filter_row.addWidget(self._btn_date_range)
        filter_row.addSpacing(16)
        filter_row.addWidget(QLabel("Trạng thái:"))
        filter_row.addWidget(self._btn_all)
        filter_row.addWidget(self._btn_drive)
        filter_row.addWidget(self._btn_local)
        filter_row.addStretch()

        lay = QVBoxLayout(self)
        lay.addLayout(row)
        lay.addLayout(filter_row)
        lay.addWidget(
            QLabel(
                "Kết quả: double-click một dòng để mở file, hoặc bấm «Lưu bản sao…» để chọn nơi lưu."
            )
        )
        lay.addWidget(self._table)

        dbp = recordings_db_path_for_search(cfg)
        self._db_ok_for_search = dbp is not None and dbp.is_file()
        if not self._db_ok_for_search:
            lay.addWidget(
                QLabel(
                    "Chưa có danh sách video — hãy cấu hình thư mục gốc quay hoặc đường dẫn theo dõi "
                    "trên máy phụ (trong Cài đặt)."
                )
            )

    def _update_date_range_button_text(self) -> None:
        a = self._date_from.toString("dd/MM/yyyy")
        b = self._date_to.toString("dd/MM/yyyy")
        self._btn_date_range.setText(f"{a} – {b}")

    def _open_date_range(self) -> None:
        min_d = QDate.currentDate().addDays(-(_DATE_RANGE_DAYS - 1))
        max_d = QDate.currentDate()
        d_from = self._date_from
        d_to = self._date_to
        if d_from < min_d:
            d_from = min_d
        if d_to > max_d:
            d_to = max_d
        if d_from > d_to:
            d_from, d_to = min_d, max_d
        dlg = _DateRangeDialog(self, d_from, d_to, min_d, max_d)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._date_from = dlg.result_from()
        self._date_to = dlg.result_to()
        self._update_date_range_button_text()
        self._run_search()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        # Spec §6.2a: không gọi setFocus() vào ô lọc — tránh máy quét COM gửi ký tự vào filter
        # khi chuyển tab Quản lý.
        if self._db_ok_for_search:
            self._run_search()

    def _run_search(self) -> None:
        dbp = recordings_db_path_for_search(self._cfg)
        if dbp is None or not dbp.is_file():
            QMessageBox.warning(
                self,
                "Chưa có danh sách",
                "Không tìm thấy file danh sách video. Hãy chọn thư mục gốc quay hoặc đường dẫn theo dõi trên máy phụ.",
            )
            return
        idx = RecordingIndex(dbp)
        idx.connect(uri_readonly=True)
        try:
            df = self._date_from.toString("yyyy-MM-dd") + "T00:00:00"
            dt = self._date_to.toString("yyyy-MM-dd") + "T23:59:59"
            if self._btn_drive.isChecked():
                rows = idx.search(
                    order_substring=self._q.text().strip(),
                    date_from=df,
                    date_to=dt,
                    storage_status="synced",
                )
            elif self._btn_local.isChecked():
                rows = idx.search(
                    order_substring=self._q.text().strip(),
                    date_from=df,
                    date_to=dt,
                    storage_status_in=["local_only", "pending_upload"],
                )
            else:
                rows = idx.search(
                    order_substring=self._q.text().strip(),
                    date_from=df,
                    date_to=dt,
                )
        finally:
            idx.close()

        self._last_rows = rows
        self._table.setRowCount(len(rows))
        app = QApplication.instance()
        trash_icon = (
            app.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
            if app is not None
            else QIcon()
        )
        for i, r in enumerate(rows):
            raw_st = r.get("storage_status", "") or ""
            path_str = r.get("resolved_path", "") or ""
            display_path = path_str
            if len(display_path) > 70:
                display_path = "…" + display_path[-67:]

            it0 = _item_optional_text(str(r.get("order_id", "") or ""))
            it1 = _item_optional_text(str(r.get("packer", "") or ""))
            it2 = _item_time_display(str(r.get("created_at", "") or ""))
            it3 = _item_duration(r.get("duration_seconds", 0))
            it4 = _item_storage_status(raw_st)
            it5 = QTableWidgetItem(display_path)
            it5.setToolTip(path_str)
            it5.setData(Qt.ItemDataRole.UserRole, path_str)

            self._table.setItem(i, 0, it0)
            self._table.setItem(i, 1, it1)
            self._table.setItem(i, 2, it2)
            self._table.setItem(i, 3, it3)
            self._table.setItem(i, 4, it4)
            self._table.setItem(i, 5, it5)

            wrap = QWidget()
            wrap_l = QHBoxLayout(wrap)
            wrap_l.setContentsMargins(0, 0, 0, 0)
            wrap_l.setSpacing(6)
            btn_copy = QPushButton("Lưu bản sao…")
            btn_copy.setStyleSheet(
                "QPushButton { font-size: 10px; padding: 2px 6px; }"
            )
            btn_copy.clicked.connect(partial(self._on_save_copy, i))
            btn_delete = QPushButton()
            btn_delete.setIcon(trash_icon)
            btn_delete.setIconSize(QSize(14, 14))
            btn_delete.setToolTip("Xóa file video và xóa khỏi danh sách.")
            btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_delete.setAccessibleName("Xóa video")
            btn_delete.setStyleSheet(
                "QPushButton {"
                "  background-color: #c62828;"
                "  border: 1px solid #b71c1c;"
                "  border-radius: 3px;"
                "  padding: 2px 4px;"
                "  min-width: 22px;"
                "  min-height: 20px;"
                "}"
                "QPushButton:hover { background-color: #e53935; }"
                "QPushButton:pressed { background-color: #8e0000; }"
            )
            btn_delete.clicked.connect(partial(self._on_delete_video, i))
            wrap_l.addWidget(btn_copy)
            wrap_l.addWidget(btn_delete)
            self._table.setCellWidget(i, 6, wrap)

        for col in (0, 1, 2, 3, 4, 6):
            self._table.resizeColumnToContents(col)

    def _on_save_copy(self, row_index: int) -> None:
        if row_index < 0 or row_index >= len(self._last_rows):
            return
        row = self._last_rows[row_index]
        src = _resolve_video_path(row)
        if src is None or not src.is_file():
            QMessageBox.warning(
                self,
                "Không tìm thấy file",
                "Không thấy file video trên máy này (có thể đã đổi ổ hoặc chưa đồng bộ).",
            )
            return
        default_name = src.name
        dst, _ = QFileDialog.getSaveFileName(
            self,
            "Lưu bản sao video",
            str(Path.home() / default_name),
            "Video (*.mp4);;Mọi file (*.*)",
        )
        if not dst:
            return
        try:
            shutil.copy2(src, dst)
        except OSError as e:
            QMessageBox.warning(self, "Không lưu được", str(e))
            return
        dst_path = Path(dst).resolve()
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Information)
        box.setWindowTitle("Đã lưu")
        box.setText(f"Đã lưu tại:\n{dst_path}")
        open_btn = box.addButton("Mở thư mục", QMessageBox.ButtonRole.ActionRole)
        box.addButton(QMessageBox.StandardButton.Ok)
        box.exec()
        if box.clickedButton() == open_btn:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(dst_path.parent)))

    def _on_double_click(self, index) -> None:
        if index.column() == 6:
            return
        r = index.row()
        if r < 0 or r >= len(self._last_rows):
            return
        row = self._last_rows[r]
        path = _resolve_video_path(row)
        if path is not None and path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
            return
        QMessageBox.information(
            self,
            "Không mở được",
            "Không tìm thấy file video tại đường dẫn đã lưu — có thể đã đổi ổ hoặc chưa đồng bộ.",
        )

    def _on_delete_video(self, row_index: int) -> None:
        if row_index < 0 or row_index >= len(self._last_rows):
            return
        row = self._last_rows[row_index]
        order = str(row.get("order_id", "") or "")
        row_id = int(row.get("id") or 0)
        if row_id <= 0:
            QMessageBox.warning(self, "Không xóa được", "Bản ghi không hợp lệ.")
            return
        src = _resolve_video_path(row)
        name = src.name if src is not None else "file không còn trên máy"
        ans = QMessageBox.question(
            self,
            "Xác nhận xóa",
            f"Xóa video {name} của đơn {order}?\n"
            "Thao tác này sẽ xóa bản ghi khỏi danh sách.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        if src is not None and src.exists():
            try:
                src.unlink()
            except OSError as e:
                QMessageBox.warning(self, "Không xóa được file", str(e))
                return
        dbp = recordings_db_path_for_search(self._cfg)
        if dbp is None or not dbp.is_file():
            QMessageBox.warning(self, "Không xóa được", "Không tìm thấy CSDL danh sách video.")
            return
        idx = RecordingIndex(dbp)
        idx.connect()
        try:
            idx.delete_by_id(row_id)
        finally:
            idx.close()
        self._run_search()


class RecordingSearchDialog(QDialog):
    """Hộp thoại độc lập; cùng nội dung nhúng tab qua RecordingSearchPanel."""

    def __init__(
        self,
        cfg: AppConfig,
        *,
        office_search_stale: bool,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tìm kiếm video đã ghi")
        self.resize(920, 520)
        lay = QVBoxLayout(self)
        self._panel = RecordingSearchPanel(
            cfg, office_search_stale=office_search_stale, parent=self
        )
        lay.addWidget(self._panel)
