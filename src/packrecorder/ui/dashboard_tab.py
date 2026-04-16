from __future__ import annotations

from datetime import datetime
from typing import Callable

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from packrecorder.dashboard_metrics import DashboardMetrics, compute_dashboard_metrics


class HourlyBarChartWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._counts = [0] * 24
        self.setMinimumHeight(180)

    def set_counts(self, counts: list[int]) -> None:
        self._counts = list(counts[:24]) + [0] * max(0, 24 - len(counts))
        self.update()

    def paintEvent(self, event) -> None:  # noqa: ANN001
        del event
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#ffffff"))
        margin = 14
        w = max(1, self.width() - 2 * margin)
        h = max(1, self.height() - 2 * margin)
        max_count = max(1, max(self._counts) if self._counts else 1)
        bar_w = max(2, w // 24 - 1)
        for i, c in enumerate(self._counts):
            x = margin + i * (bar_w + 1)
            bh = int((float(c) / float(max_count)) * (h - 18))
            y = margin + (h - bh)
            p.fillRect(x, y, bar_w, bh, QColor("#1976d2"))
        p.end()


class DashboardTab(QWidget):
    def __init__(
        self,
        *,
        fetch_rows: Callable[[str, str, str | None], list[dict]],
        fetch_packers: Callable[[str, str], list[str]],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._fetch_rows = fetch_rows
        self._fetch_packers = fetch_packers
        today = QDate.currentDate()
        self._from_date = QDateEdit(today.addDays(-6), self)
        self._to_date = QDateEdit(today, self)
        self._from_date.setDisplayFormat("dd/MM/yyyy")
        self._to_date.setDisplayFormat("dd/MM/yyyy")
        self._from_date.setCalendarPopup(True)
        self._to_date.setCalendarPopup(True)
        self._packer = QComboBox(self)
        self._packer.addItem("Tất cả")
        self._quick_range = QComboBox(self)
        self._quick_range.addItems(
            [
                "Hôm nay",
                "Hôm qua",
                "7 ngày gần nhất",
                "30 ngày gần nhất",
                "Tháng này",
                "Quý này",
                "Năm nay",
                "Ngày tùy chọn",
            ]
        )
        self._quick_range.currentTextChanged.connect(self._on_quick_range_changed)
        self._btn_refresh = QPushButton("Làm mới", self)
        self._btn_refresh.clicked.connect(self.refresh_data)

        filter_form = QFormLayout()
        filter_form.addRow("Bộ lọc nhanh", self._quick_range)
        filter_form.addRow("Từ ngày", self._from_date)
        filter_form.addRow("Đến ngày", self._to_date)
        filter_form.addRow("Nhân viên / quầy", self._packer)
        top_wrap = QWidget(self)
        top_row = QHBoxLayout(top_wrap)
        top_row.setContentsMargins(0, 0, 0, 0)
        top_row.addLayout(filter_form)
        top_row.addWidget(self._btn_refresh, 0, Qt.AlignmentFlag.AlignBottom)
        top_row.addStretch()

        self._kpi_total = self._make_card("Tổng đơn", "0")
        self._kpi_speed = self._make_card("Tốc độ TB", "0s/đơn")
        self._kpi_idle = self._make_card("Idle TB", "0s")
        self._kpi_pending = self._make_card("Chờ đồng bộ", "0")
        card_grid = QGridLayout()
        card_grid.addWidget(self._kpi_total, 0, 0)
        card_grid.addWidget(self._kpi_speed, 0, 1)
        card_grid.addWidget(self._kpi_idle, 0, 2)
        card_grid.addWidget(self._kpi_pending, 0, 3)

        self._chart = HourlyBarChartWidget(self)
        self._table = QTableWidget(0, 7, self)
        self._table.setHorizontalHeaderLabels(
            ["Mã đơn", "Người gói", "Thời gian", "Thời lượng (s)", "Trạng thái", "Máy", "Quầy"]
        )

        root = QVBoxLayout(self)
        root.addWidget(top_wrap)
        root.addLayout(card_grid)
        root.addWidget(QLabel("Sản lượng theo khung giờ (0-23h)"))
        root.addWidget(self._chart)
        root.addWidget(self._table, 1)

        self._on_quick_range_changed(self._quick_range.currentText())
        self.refresh_data()

    def _make_card(self, title: str, value: str) -> QFrame:
        frame = QFrame(self)
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        lay = QVBoxLayout(frame)
        title_lb = QLabel(title, frame)
        title_lb.setStyleSheet("color:#546e7a;")
        value_lb = QLabel(value, frame)
        value_lb.setStyleSheet("font-size:18px;font-weight:700;")
        value_lb.setProperty("kpi_value", True)
        lay.addWidget(title_lb)
        lay.addWidget(value_lb)
        return frame

    def _set_card_value(self, card: QFrame, text: str) -> None:
        for child in card.findChildren(QLabel):
            if bool(child.property("kpi_value")):
                child.setText(text)
                return

    def refresh_data(self) -> None:
        d_from = self._from_date.date()
        d_to = self._to_date.date()
        if d_from > d_to:
            d_from, d_to = d_to, d_from
            self._from_date.setDate(d_from)
            self._to_date.setDate(d_to)
        from_iso = d_from.toString("yyyy-MM-dd") + "T00:00:00"
        to_iso = d_to.toString("yyyy-MM-dd") + "T23:59:59"
        selected = self._packer.currentText().strip()
        packer = None if selected in ("", "Tất cả") else selected
        rows = self._fetch_rows(from_iso, to_iso, packer)
        metrics = compute_dashboard_metrics(rows)
        self._render_metrics(metrics)
        self._reload_packer_options(from_iso, to_iso)

    def _on_quick_range_changed(self, label: str) -> None:
        today = QDate.currentDate()
        from_d = today
        to_d = today
        if label == "Hôm qua":
            from_d = today.addDays(-1)
            to_d = from_d
        elif label == "7 ngày gần nhất":
            from_d = today.addDays(-6)
        elif label == "30 ngày gần nhất":
            from_d = today.addDays(-29)
        elif label == "Tháng này":
            from_d = QDate(today.year(), today.month(), 1)
        elif label == "Quý này":
            start_month = ((today.month() - 1) // 3) * 3 + 1
            from_d = QDate(today.year(), start_month, 1)
        elif label == "Năm nay":
            from_d = QDate(today.year(), 1, 1)
        elif label == "Ngày tùy chọn":
            # Giữ nguyên ngày người dùng đang nhập tay.
            return
        self._from_date.setDate(from_d)
        self._to_date.setDate(to_d)
        self.refresh_data()

    def _reload_packer_options(self, from_iso: str, to_iso: str) -> None:
        current = self._packer.currentText().strip()
        options = self._fetch_packers(from_iso, to_iso)
        self._packer.blockSignals(True)
        self._packer.clear()
        self._packer.addItem("Tất cả")
        for op in options:
            self._packer.addItem(op)
        idx = self._packer.findText(current)
        self._packer.setCurrentIndex(max(0, idx))
        self._packer.blockSignals(False)

    def _render_metrics(self, metrics: DashboardMetrics) -> None:
        self._set_card_value(self._kpi_total, str(metrics.total_orders))
        self._set_card_value(self._kpi_speed, f"{metrics.avg_duration_seconds:.1f}s/đơn")
        self._set_card_value(self._kpi_idle, f"{metrics.avg_idle_seconds:.1f}s")
        self._set_card_value(
            self._kpi_pending,
            f"{metrics.pending_sync_count} (synced {metrics.synced_count})",
        )
        self._chart.set_counts(metrics.hourly_counts)
        self._table.setRowCount(len(metrics.detail_rows))
        for i, row in enumerate(metrics.detail_rows):
            vals = [
                str(row.get("order_id") or ""),
                str(row.get("packer") or ""),
                str(row.get("created_at") or ""),
                f"{float(row.get('duration_seconds') or 0.0):.1f}",
                str(row.get("storage_status") or ""),
                str(row.get("machine_id") or ""),
                str(row.get("station_name") or ""),
            ]
            for col, value in enumerate(vals):
                self._table.setItem(i, col, QTableWidgetItem(value))
