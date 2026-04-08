from __future__ import annotations

import shutil
from functools import partial
from pathlib import Path

from PySide6.QtCore import QDate, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from packrecorder.config import AppConfig
from packrecorder.recording_index import RecordingIndex, preferred_index_path


def recordings_db_path(cfg: AppConfig) -> Path | None:
    if (cfg.video_root or "").strip():
        return preferred_index_path(cfg)
    r = (cfg.remote_status_json_path or "").strip()
    if r:
        return Path(r).parent / "recordings.sqlite"
    return None


def _label_for_storage_status(raw: str) -> str:
    return {
        "synced": "Đã đồng bộ lên ổ chính",
        "pending_upload": "Đang chờ đẩy lên ổ chính",
        "local_only": "Chỉ lưu trên máy / ổ dự phòng",
    }.get(raw, raw)


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


class RecordingSearchDialog(QDialog):
    def __init__(
        self,
        cfg: AppConfig,
        *,
        office_search_stale: bool,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Tìm kiếm video đã ghi")
        self.resize(920, 520)
        self._cfg = cfg
        self._last_rows: list[dict] = []

        if office_search_stale:
            QMessageBox.information(
                self,
                "Dữ liệu",
                "Dữ liệu đang bị trễ. Vui lòng kiểm tra máy đóng gói hoặc liên hệ kỹ thuật.",
            )

        self._q = QLineEdit()
        self._q.setPlaceholderText("Mã đơn, tên người gói…")
        self._from = QDateEdit()
        self._from.setCalendarPopup(True)
        self._from.setDate(QDate.currentDate().addYears(-1))
        self._to = QDateEdit()
        self._to.setCalendarPopup(True)
        self._to.setDate(QDate.currentDate())
        self._status = QComboBox()
        self._status.addItem("(Tất cả)", "")
        self._status.addItem("Đã đồng bộ lên ổ chính", "synced")
        self._status.addItem("Đang chờ đẩy lên ổ chính", "pending_upload")
        self._status.addItem("Chỉ lưu trên máy / ổ dự phòng", "local_only")

        self._table = QTableWidget(0, 6)
        self._table.setAlternatingRowColors(True)
        self._table.setHorizontalHeaderLabels(
            ["Mã đơn", "Người gói", "Trạng thái", "Thời gian", "File video", "Thao tác"]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.doubleClicked.connect(self._on_double_click)

        search_btn = QPushButton("Tìm")
        search_btn.setDefault(True)
        search_btn.clicked.connect(self._run_search)
        row = QHBoxLayout()
        row.addWidget(self._q)
        row.addWidget(search_btn)

        filter_row = QHBoxLayout()
        filter_row.addWidget(QLabel("Từ"))
        filter_row.addWidget(self._from)
        filter_row.addWidget(QLabel("đến"))
        filter_row.addWidget(self._to)
        filter_row.addSpacing(12)
        filter_row.addWidget(QLabel("Trạng thái:"))
        filter_row.addWidget(self._status, stretch=1)
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

        dbp = recordings_db_path(cfg)
        if dbp is None or not dbp.is_file():
            lay.addWidget(
                QLabel(
                    "Chưa có danh sách video — hãy cấu hình thư mục gốc quay hoặc đường dẫn theo dõi "
                    "trên máy phụ (trong Cài đặt)."
                )
            )

    def _run_search(self) -> None:
        dbp = recordings_db_path(self._cfg)
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
            df = self._from.date().toString("yyyy-MM-dd") + "T00:00:00"
            dt = self._to.date().toString("yyyy-MM-dd") + "T23:59:59"
            st = self._status.currentData()
            rows = idx.search(
                order_substring=self._q.text().strip(),
                date_from=df,
                date_to=dt,
                storage_status=st if st else None,
            )
        finally:
            idx.close()

        self._last_rows = rows
        self._table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            raw_st = r.get("storage_status", "") or ""
            path_str = r.get("resolved_path", "") or ""
            path = Path(path_str)
            display_path = path_str
            if len(display_path) > 70:
                display_path = "…" + display_path[-67:]

            it0 = QTableWidgetItem(r.get("order_id", ""))
            it1 = QTableWidgetItem(r.get("packer", ""))
            it2 = QTableWidgetItem(_label_for_storage_status(raw_st))
            it3 = QTableWidgetItem(r.get("created_at", ""))
            it4 = QTableWidgetItem(display_path)
            it4.setToolTip(path_str)
            it4.setData(Qt.ItemDataRole.UserRole, path_str)

            self._table.setItem(i, 0, it0)
            self._table.setItem(i, 1, it1)
            self._table.setItem(i, 2, it2)
            self._table.setItem(i, 3, it3)
            self._table.setItem(i, 4, it4)

            btn = QPushButton("Lưu bản sao…")
            btn.clicked.connect(partial(self._on_save_copy, i))
            self._table.setCellWidget(i, 5, btn)

        self._table.resizeColumnsToContents()
        self._table.horizontalHeader().setStretchLastSection(True)

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
        if index.column() == 5:
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
