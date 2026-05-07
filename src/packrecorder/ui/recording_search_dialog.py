from __future__ import annotations

import shutil
from datetime import datetime
from dataclasses import dataclass
from functools import partial
from pathlib import Path
import re
from typing import Callable

from PySide6.QtCore import QDate, QSize, Qt, QUrl, Signal
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
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
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
    QSpinBox,
    QSlider,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from packrecorder.config import AppConfig
from packrecorder.recording_index import RecordingIndex, recordings_db_path_for_search

# Cửa sổ 16 ngày gần nhất (kể cả hôm nay): today-15 … today
_DATE_RANGE_DAYS = 16
_CAM_SUFFIX_RE = re.compile(r"(?:^|[_-])cam(\d+)(?:\.[A-Za-z0-9]+)?$", re.IGNORECASE)


@dataclass
class _ViewerClip:
    cam_index: int | None
    cam_label: str
    path: Path


def _parse_cam_index_from_row(row: dict) -> int | None:
    for key in ("rel_key", "resolved_path"):
        raw = str(row.get(key) or "").strip()
        if not raw:
            continue
        m = _CAM_SUFFIX_RE.search(Path(raw).stem)
        if m:
            try:
                return int(m.group(1))
            except (TypeError, ValueError):
                return None
    return None


def _group_key_for_row(row: dict) -> tuple[str, str, str]:
    order = str(row.get("order_id") or "").strip()
    packer = str(row.get("packer") or "").strip()
    created = str(row.get("created_at") or "").strip()
    return (order, packer, created)


class MultiCamViewerDialog(QDialog):
    def __init__(self, clips: list[_ViewerClip], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Xem video đa camera")
        self.resize(1080, 720)
        self._clips = list(clips)
        self._players: list[QMediaPlayer] = []
        self._audios: list[QAudioOutput] = []
        self._grid_videos: list[QVideoWidget] = []
        self._active_idx = 0
        self._last_position_ms = 0
        self._single_mode = True
        self._cam_buttons: list[QToolButton] = []
        self._seeking = False

        self._stack = QStackedWidget(self)
        self._single_video = QVideoWidget(self)
        self._single_video.setMinimumHeight(360)
        self._stack.addWidget(self._single_video)
        self._grid_wrap = QWidget(self)
        self._grid_layout = QGridLayout(self._grid_wrap)
        self._grid_layout.setContentsMargins(0, 0, 0, 0)
        self._grid_layout.setSpacing(8)
        self._stack.addWidget(self._grid_wrap)

        self._play_btn = QPushButton("Play")
        self._play_btn.clicked.connect(self._toggle_play_pause)
        self._mode_btn = QPushButton("Xem lưới")
        self._mode_btn.clicked.connect(self._toggle_mode)
        self._seek = QSlider(Qt.Orientation.Horizontal)
        self._seek.setRange(0, 0)
        self._seek.sliderPressed.connect(self._on_seek_pressed)
        self._seek.sliderReleased.connect(self._on_seek_released)
        self._seek.sliderMoved.connect(self._on_seek_moved)
        self._time_lbl = QLabel("00:00 / 00:00")
        self._time_lbl.setMinimumWidth(120)
        self._time_lbl.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        cam_row = QHBoxLayout()
        cam_row.setContentsMargins(0, 0, 0, 0)
        cam_row.setSpacing(6)
        for i, clip in enumerate(self._clips):
            b = QToolButton(self)
            b.setText(clip.cam_label)
            b.setCheckable(True)
            b.clicked.connect(lambda _checked=False, idx=i: self._switch_camera(idx))
            self._cam_buttons.append(b)
            cam_row.addWidget(b)
        cam_row.addStretch(1)
        cam_row.addWidget(self._mode_btn)

        ctl = QHBoxLayout()
        ctl.setContentsMargins(0, 0, 0, 0)
        ctl.addWidget(self._play_btn)
        ctl.addWidget(self._seek, 1)
        ctl.addWidget(self._time_lbl)

        lay = QVBoxLayout(self)
        lay.addLayout(cam_row)
        lay.addWidget(self._stack, 1)
        lay.addLayout(ctl)

        self._init_players()
        self._refresh_cam_buttons()
        self._sync_ui_time()

    @staticmethod
    def _fmt_ms(ms: int) -> str:
        s = max(0, int(ms // 1000))
        m, ss = divmod(s, 60)
        h, mm = divmod(m, 60)
        if h > 0:
            return f"{h:02d}:{mm:02d}:{ss:02d}"
        return f"{mm:02d}:{ss:02d}"

    def _init_players(self) -> None:
        for clip in self._clips:
            audio = QAudioOutput(self)
            audio.setVolume(0.6)
            player = QMediaPlayer(self)
            player.setAudioOutput(audio)
            player.setSource(QUrl.fromLocalFile(str(clip.path.resolve())))
            self._audios.append(audio)
            self._players.append(player)
            vw = QVideoWidget(self._grid_wrap)
            vw.setMinimumSize(260, 180)
            self._grid_videos.append(vw)
            idx = len(self._players) - 1
            r = idx // 2
            c = idx % 2
            self._grid_layout.addWidget(vw, r, c)
        self._apply_video_outputs()
        if self._players:
            self._bind_master_signals(self._players[self._active_idx])

    def _bind_master_signals(self, player: QMediaPlayer) -> None:
        player.positionChanged.connect(self._on_master_position_changed)
        player.durationChanged.connect(self._on_master_duration_changed)

    def _apply_video_outputs(self) -> None:
        for i, p in enumerate(self._players):
            if self._single_mode:
                if i == self._active_idx:
                    p.setVideoOutput(self._single_video)
                else:
                    p.setVideoOutput(None)
            else:
                if i < len(self._grid_videos):
                    p.setVideoOutput(self._grid_videos[i])

    def _master_player(self) -> QMediaPlayer | None:
        if not self._players:
            return None
        return self._players[self._active_idx]

    def _capture_current_progress(self) -> tuple[int, bool]:
        p = self._master_player()
        if p is None:
            return (self._last_position_ms, False)
        state = p.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        pos = int(p.position())
        self._last_position_ms = max(0, pos)
        return (self._last_position_ms, state)

    def _apply_progress_to_all(self, position_ms: int, play: bool) -> None:
        for p in self._players:
            p.setPosition(max(0, int(position_ms)))
            if play:
                p.play()
            else:
                p.pause()
        self._sync_ui_time()

    def _refresh_cam_buttons(self) -> None:
        for i, b in enumerate(self._cam_buttons):
            b.setChecked(i == self._active_idx)

    def _switch_camera(self, idx: int) -> None:
        if not (0 <= idx < len(self._players)) or idx == self._active_idx:
            return
        pos, was_playing = self._capture_current_progress()
        self._active_idx = idx
        cur = self._players[self._active_idx]
        self._bind_master_signals(cur)
        self._apply_video_outputs()
        cur.setPosition(pos)
        if was_playing:
            cur.play()
        else:
            cur.pause()
        self._refresh_cam_buttons()
        self._sync_ui_time()

    def _toggle_mode(self) -> None:
        pos, was_playing = self._capture_current_progress()
        self._single_mode = not self._single_mode
        self._mode_btn.setText("Xem lưới" if self._single_mode else "Xem 1 cam")
        self._stack.setCurrentIndex(0 if self._single_mode else 1)
        self._apply_video_outputs()
        self._apply_progress_to_all(pos, was_playing)

    def _toggle_play_pause(self) -> None:
        p = self._master_player()
        if p is None:
            return
        play = p.playbackState() != QMediaPlayer.PlaybackState.PlayingState
        self._apply_progress_to_all(self._capture_current_progress()[0], play)
        self._play_btn.setText("Pause" if play else "Play")

    def _sync_ui_time(self) -> None:
        p = self._master_player()
        if p is None:
            self._time_lbl.setText("00:00 / 00:00")
            self._seek.setRange(0, 0)
            return
        pos = int(p.position())
        dur = max(0, int(p.duration()))
        if not self._seeking:
            self._seek.setRange(0, dur)
            self._seek.setValue(pos)
        self._time_lbl.setText(f"{self._fmt_ms(pos)} / {self._fmt_ms(dur)}")

    def _on_master_position_changed(self, _pos: int) -> None:
        self._sync_ui_time()

    def _on_master_duration_changed(self, _dur: int) -> None:
        self._sync_ui_time()

    def _on_seek_pressed(self) -> None:
        self._seeking = True

    def _on_seek_moved(self, _pos: int) -> None:
        self._sync_ui_time()

    def _on_seek_released(self) -> None:
        self._seeking = False
        target = int(self._seek.value())
        pos, was_playing = self._capture_current_progress()
        _ = pos
        self._apply_progress_to_all(target, was_playing)


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
    retention_controls_changed = Signal(bool, int)

    def __init__(
        self,
        cfg: AppConfig,
        *,
        office_search_stale: bool,
        retention_enabled: bool | None = None,
        on_retention_controls_changed: Callable[[bool, int], None] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._last_rows: list[dict] = []
        self._table_row_meta: list[dict] = []
        self._grouped_rows: list[dict] = []
        self._on_retention_controls_changed = on_retention_controls_changed

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

        keep_days = max(1, int(self._cfg.video_retention_keep_days or 0))
        self._retention_enabled = (
            bool(retention_enabled)
            if retention_enabled is not None
            else int(self._cfg.video_retention_keep_days or 0) > 0
        )
        self._retention_checkbox = QCheckBox("Tự xóa video sau")
        self._retention_checkbox.setChecked(self._retention_enabled)
        self._retention_days = QSpinBox()
        self._retention_days.setRange(1, 3650)
        self._retention_days.setValue(keep_days)
        self._retention_days.setEnabled(self._retention_enabled)
        self._retention_days.setSuffix(" ngày")
        self._retention_checkbox.toggled.connect(self._on_retention_toggled)
        self._retention_days.valueChanged.connect(self._on_retention_value_changed)
        if self._on_retention_controls_changed is not None:
            self.retention_controls_changed.connect(self._on_retention_controls_changed)

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
                "Kết quả: double-click dòng cha để xem đa cam trong app; dòng con vẫn hỗ trợ mở/tải/xóa từng file."
            )
        )
        lay.addWidget(self._table)
        retention_row = QHBoxLayout()
        retention_row.setContentsMargins(0, 0, 0, 0)
        retention_row.setSpacing(8)
        retention_row.addWidget(self._retention_checkbox)
        retention_row.addWidget(self._retention_days)
        retention_row.addStretch()
        lay.addLayout(retention_row)

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

    def _build_grouped_rows(self, rows: list[dict]) -> list[dict]:
        grouped: dict[tuple[str, str, str], list[dict]] = {}
        for r in rows:
            key = _group_key_for_row(r)
            grouped.setdefault(key, []).append(r)
        out: list[dict] = []
        for key, members in grouped.items():
            sorted_members = sorted(
                members,
                key=lambda row: (
                    (_parse_cam_index_from_row(row) is None),
                    int(_parse_cam_index_from_row(row) or 999),
                    str(row.get("resolved_path") or ""),
                ),
            )
            clips: list[_ViewerClip] = []
            for m in sorted_members:
                p = _resolve_video_path(m)
                if p is None or not p.is_file():
                    continue
                cam_idx = _parse_cam_index_from_row(m)
                label = f"Cam {cam_idx}" if cam_idx is not None else f"Cam {len(clips)+1}"
                clips.append(_ViewerClip(cam_idx, label, p))
            out.append(
                {
                    "key": key,
                    "rows": sorted_members,
                    "cam_count": len(sorted_members),
                    "clips": clips,
                    "order_id": key[0],
                    "packer": key[1],
                    "created_at": key[2],
                }
            )
        out.sort(key=lambda g: str(g.get("created_at") or ""), reverse=True)
        return out

    def _open_group_viewer(self, group_idx: int, *, preferred_cam: int | None = None) -> None:
        if not (0 <= group_idx < len(self._grouped_rows)):
            return
        g = self._grouped_rows[group_idx]
        clips = list(g.get("clips") or [])
        if not clips:
            QMessageBox.information(
                self,
                "Không mở được",
                "Không tìm thấy file video khả dụng để xem trong app.",
            )
            return
        if preferred_cam is not None:
            clips.sort(
                key=lambda c: (
                    c.cam_index is None,
                    0 if c.cam_index == preferred_cam else 1,
                    int(c.cam_index or 0),
                )
            )
        dlg = MultiCamViewerDialog(clips, self)
        dlg.exec()

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
        self._grouped_rows = self._build_grouped_rows(rows)
        self._table_row_meta = []
        total_display_rows = sum(1 + len(g["rows"]) for g in self._grouped_rows)
        self._table.setRowCount(total_display_rows)
        app = QApplication.instance()
        trash_icon = (
            app.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
            if app is not None
            else QIcon()
        )
        app_style = app.style() if app is not None else None
        download_icon = (
            app_style.standardIcon(QStyle.StandardPixmap.SP_ArrowDown)
            if app_style is not None
            else QIcon()
        )
        folder_icon = (
            app_style.standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon)
            if app_style is not None
            else QIcon()
        )
        row_i = 0
        for group_idx, group in enumerate(self._grouped_rows):
            order = str(group.get("order_id") or "")
            packer = str(group.get("packer") or "")
            created = str(group.get("created_at") or "")
            cam_count = int(group.get("cam_count") or 0)
            if cam_count <= 1 and group["rows"]:
                child = group["rows"][0]
                raw_st = child.get("storage_status", "") or ""
                path_str = child.get("resolved_path", "") or ""
                display_path = path_str
                if len(display_path) > 70:
                    display_path = "…" + display_path[-67:]
                it0 = _item_optional_text(str(child.get("order_id", "") or ""))
                it1 = _item_optional_text(str(child.get("packer", "") or ""))
                it2 = _item_time_display(str(child.get("created_at", "") or ""))
                it3 = _item_duration(child.get("duration_seconds", 0))
                it4 = _item_storage_status(raw_st)
                it5 = QTableWidgetItem(display_path)
                it5.setToolTip(path_str)
                it5.setData(Qt.ItemDataRole.UserRole, path_str)

                self._table.setItem(row_i, 0, it0)
                self._table.setItem(row_i, 1, it1)
                self._table.setItem(row_i, 2, it2)
                self._table.setItem(row_i, 3, it3)
                self._table.setItem(row_i, 4, it4)
                self._table.setItem(row_i, 5, it5)

                wrap = QWidget()
                wrap_l = QHBoxLayout(wrap)
                wrap_l.setContentsMargins(0, 0, 0, 0)
                wrap_l.setSpacing(2)
                btn_download = QToolButton()
                btn_download.setIcon(download_icon)
                btn_download.setIconSize(QSize(16, 16))
                btn_download.setToolTip("Tải video")
                btn_download.setAccessibleName("Tải video")
                btn_download.setAutoRaise(True)
                btn_download.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_download.clicked.connect(partial(self._on_save_copy, row_i))
                btn_open_folder = QToolButton()
                btn_open_folder.setIcon(folder_icon)
                btn_open_folder.setIconSize(QSize(16, 16))
                btn_open_folder.setToolTip("Mở folder")
                btn_open_folder.setAccessibleName("Mở folder")
                btn_open_folder.setAutoRaise(True)
                btn_open_folder.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_open_folder.clicked.connect(partial(self._on_open_folder, row_i))
                btn_delete = QToolButton()
                btn_delete.setIcon(trash_icon)
                btn_delete.setIconSize(QSize(16, 16))
                btn_delete.setToolTip("Xóa file video và xóa khỏi danh sách.")
                btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_delete.setAccessibleName("Xóa video")
                btn_delete.setAutoRaise(True)
                btn_delete.clicked.connect(partial(self._on_delete_video, row_i))
                wrap_l.addWidget(btn_download)
                wrap_l.addWidget(btn_open_folder)
                wrap_l.addWidget(btn_delete)
                self._table.setCellWidget(row_i, 6, wrap)
                self._table_row_meta.append({"type": "child", "row": child, "group_idx": group_idx, "cam_idx": _parse_cam_index_from_row(child)})
                row_i += 1
                continue
            parent_order = QTableWidgetItem(f"{order} ({cam_count} cam)")
            f = parent_order.font()
            f.setBold(True)
            parent_order.setFont(f)
            parent_order.setForeground(QBrush(QColor("#1f3a5f")))
            self._table.setItem(row_i, 0, parent_order)
            self._table.setItem(row_i, 1, _item_optional_text(packer))
            self._table.setItem(row_i, 2, _item_time_display(created))
            total_duration = sum(float(r.get("duration_seconds") or 0.0) for r in group["rows"])
            self._table.setItem(row_i, 3, _item_duration(total_duration))
            self._table.setItem(row_i, 4, QTableWidgetItem("Nhóm đa-cam" if cam_count > 1 else "1 cam"))
            self._table.setItem(row_i, 5, QTableWidgetItem("Xem trong app"))
            wrap_parent = QWidget()
            wp = QHBoxLayout(wrap_parent)
            wp.setContentsMargins(0, 0, 0, 0)
            btn_view = QToolButton()
            btn_view.setText("Xem")
            btn_view.setToolTip("Mở trình xem nhiều camera trong app")
            btn_view.clicked.connect(partial(self._open_group_viewer, group_idx))
            wp.addWidget(btn_view)
            self._table.setCellWidget(row_i, 6, wrap_parent)
            self._table_row_meta.append({"type": "group", "group_idx": group_idx})
            row_i += 1

            for child in group["rows"]:
                raw_st = child.get("storage_status", "") or ""
                path_str = child.get("resolved_path", "") or ""
                display_path = path_str
                if len(display_path) > 70:
                    display_path = "…" + display_path[-67:]
                cam_idx = _parse_cam_index_from_row(child)
                cam_txt = f"  ↳ Cam {cam_idx}" if cam_idx is not None else "  ↳ Camera"
                it0 = QTableWidgetItem(cam_txt)
                it0.setForeground(QBrush(QColor("#555555")))
                self._table.setItem(row_i, 0, it0)
                self._table.setItem(row_i, 1, _item_optional_text(str(child.get("packer", "") or "")))
                self._table.setItem(row_i, 2, _item_time_display(str(child.get("created_at", "") or "")))
                self._table.setItem(row_i, 3, _item_duration(child.get("duration_seconds", 0)))
                self._table.setItem(row_i, 4, _item_storage_status(raw_st))
                it5 = QTableWidgetItem(display_path)
                it5.setToolTip(path_str)
                it5.setData(Qt.ItemDataRole.UserRole, path_str)
                self._table.setItem(row_i, 5, it5)

                wrap = QWidget()
                wrap_l = QHBoxLayout(wrap)
                wrap_l.setContentsMargins(0, 0, 0, 0)
                wrap_l.setSpacing(2)
                btn_view_cam = QToolButton()
                btn_view_cam.setText("Xem")
                btn_view_cam.setToolTip("Mở viewer tại camera này")
                btn_view_cam.clicked.connect(partial(self._open_group_viewer, group_idx, preferred_cam=cam_idx))
                btn_download = QToolButton()
                btn_download.setIcon(download_icon)
                btn_download.setIconSize(QSize(16, 16))
                btn_download.setToolTip("Tải video")
                btn_download.setAccessibleName("Tải video")
                btn_download.setAutoRaise(True)
                btn_download.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_download.clicked.connect(partial(self._on_save_copy, row_i))
                btn_open_folder = QToolButton()
                btn_open_folder.setIcon(folder_icon)
                btn_open_folder.setIconSize(QSize(16, 16))
                btn_open_folder.setToolTip("Mở folder")
                btn_open_folder.setAccessibleName("Mở folder")
                btn_open_folder.setAutoRaise(True)
                btn_open_folder.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_open_folder.clicked.connect(partial(self._on_open_folder, row_i))
                btn_delete = QToolButton()
                btn_delete.setIcon(trash_icon)
                btn_delete.setIconSize(QSize(16, 16))
                btn_delete.setToolTip("Xóa file video và xóa khỏi danh sách.")
                btn_delete.setCursor(Qt.CursorShape.PointingHandCursor)
                btn_delete.setAccessibleName("Xóa video")
                btn_delete.setAutoRaise(True)
                btn_delete.clicked.connect(partial(self._on_delete_video, row_i))
                wrap_l.addWidget(btn_view_cam)
                wrap_l.addWidget(btn_download)
                wrap_l.addWidget(btn_open_folder)
                wrap_l.addWidget(btn_delete)
                self._table.setCellWidget(row_i, 6, wrap)
                self._table_row_meta.append({"type": "child", "row": child, "group_idx": group_idx, "cam_idx": cam_idx})
                row_i += 1

        for col in (0, 1, 2, 3, 4, 6):
            self._table.resizeColumnToContents(col)

    def _on_save_copy(self, row_index: int) -> None:
        if row_index < 0 or row_index >= len(self._table_row_meta):
            return
        meta = self._table_row_meta[row_index]
        if meta.get("type") != "child":
            return
        row = dict(meta.get("row") or {})
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

    def _on_open_folder(self, row_index: int) -> None:
        if row_index < 0 or row_index >= len(self._table_row_meta):
            return
        meta = self._table_row_meta[row_index]
        if meta.get("type") != "child":
            return
        row = dict(meta.get("row") or {})
        src = _resolve_video_path(row)
        if src is None:
            QMessageBox.warning(
                self,
                "Không tìm thấy file",
                "Không thấy file video trên máy này (có thể đã đổi ổ hoặc chưa đồng bộ).",
            )
            return
        if src.parent.is_dir():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(src.parent.resolve())))
            return
        QMessageBox.warning(self, "Không mở được folder", "Thư mục chứa file không tồn tại.")

    def _on_retention_toggled(self, checked: bool) -> None:
        self._retention_days.setEnabled(checked)
        self.retention_controls_changed.emit(bool(checked), int(self._retention_days.value()))

    def _on_retention_value_changed(self, value: int) -> None:
        self.retention_controls_changed.emit(
            bool(self._retention_checkbox.isChecked()), int(value)
        )

    def append_query_text(self, raw: str) -> None:
        txt = str(raw or "")
        if not txt:
            return
        self._q.setText(self._q.text() + txt)
        self._q.setCursorPosition(len(self._q.text()))

    def query_input_has_focus(self) -> bool:
        return self._q.hasFocus()

    def _on_double_click(self, index) -> None:
        if index.column() == 6:
            return
        r = index.row()
        if r < 0 or r >= len(self._table_row_meta):
            return
        meta = self._table_row_meta[r]
        if meta.get("type") == "group":
            self._open_group_viewer(int(meta.get("group_idx") or 0))
            return
        if meta.get("type") != "child":
            return
        row = dict(meta.get("row") or {})
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
        if row_index < 0 or row_index >= len(self._table_row_meta):
            return
        meta = self._table_row_meta[row_index]
        if meta.get("type") != "child":
            return
        row = dict(meta.get("row") or {})
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
