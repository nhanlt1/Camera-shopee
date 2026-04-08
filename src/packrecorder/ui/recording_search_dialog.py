from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDate, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QDialog,
    QFormLayout,
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
        self.resize(900, 480)
        self._cfg = cfg
        if office_search_stale:
            QMessageBox.information(
                self,
                "Dữ liệu",
                "Dữ liệu đang bị trễ. Vui lòng kiểm tra máy đóng gói hoặc liên hệ kỹ thuật.",
            )

        self._q = QLineEdit()
        self._q.setPlaceholderText("Mã đơn, nhãn gói…")
        self._from = QDateEdit()
        self._from.setCalendarPopup(True)
        self._from.setDate(QDate.currentDate().addYears(-1))
        self._to = QDateEdit()
        self._to.setCalendarPopup(True)
        self._to.setDate(QDate.currentDate())
        self._status = QComboBox()
        self._status.addItem("(Tất cả)", "")
        self._status.addItem("synced", "synced")
        self._status.addItem("pending_upload", "pending_upload")
        self._status.addItem("local_only", "local_only")

        self._table = QTableWidget(0, 6)
        self._table.setHorizontalHeaderLabels(
            ["Mã đơn", "Nhãn", "Trạng thái", "Tạo lúc", "Đường dẫn", "rel_key"]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.doubleClicked.connect(self._on_double_click)

        search_btn = QPushButton("Tìm")
        search_btn.clicked.connect(self._run_search)
        row = QHBoxLayout()
        row.addWidget(self._q)
        row.addWidget(search_btn)

        form = QFormLayout()
        form.addRow("Từ ngày", self._from)
        form.addRow("Đến ngày", self._to)
        form.addRow("Trạng thái lưu", self._status)

        lay = QVBoxLayout(self)
        lay.addLayout(row)
        lay.addLayout(form)
        lay.addWidget(QLabel("Kết quả (double-click để mở file):"))
        lay.addWidget(self._table)

        dbp = recordings_db_path(cfg)
        if dbp is None or not dbp.is_file():
            lay.addWidget(
                QLabel(
                    "Chưa có đường dẫn tới recordings.sqlite — cấu hình thư mục gốc video "
                    "hoặc đường dẫn status.json máy phụ."
                )
            )

    def _run_search(self) -> None:
        dbp = recordings_db_path(self._cfg)
        if dbp is None or not dbp.is_file():
            QMessageBox.warning(self, "Thiếu CSDL", "Không tìm thấy file recordings.sqlite.")
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

        self._table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self._table.setItem(i, 0, QTableWidgetItem(r.get("order_id", "")))
            self._table.setItem(i, 1, QTableWidgetItem(r.get("packer", "")))
            self._table.setItem(i, 2, QTableWidgetItem(r.get("storage_status", "")))
            self._table.setItem(i, 3, QTableWidgetItem(r.get("created_at", "")))
            self._table.setItem(i, 4, QTableWidgetItem(r.get("resolved_path", "")))
            self._table.setItem(i, 5, QTableWidgetItem(r.get("rel_key", "")))
        self._table.resizeColumnsToContents()

    def _on_double_click(self) -> None:
        r = self._table.currentRow()
        if r < 0:
            return
        item_res = self._table.item(r, 4)
        if item_res is None:
            return
        path = Path(item_res.text())
        if path.is_file():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(path.resolve())))
            return
        # thử primary_root / rel_key nếu có trong row — đọc lại từ DB phức tạp; mở explorer thư mục gốc
        QMessageBox.information(
            self,
            "Không mở được",
            "File không còn tại đường dẫn đã ghi — có thể đã đổi ổ hoặc chưa đồng bộ.",
        )
