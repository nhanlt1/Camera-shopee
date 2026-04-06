from __future__ import annotations

import shutil
from dataclasses import replace
from datetime import date, datetime, time as time_cls
from functools import partial
from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QMainWindow, QMenu, QMessageBox, QStatusBar

from packrecorder.config import (
    AppConfig,
    StationConfig,
    default_config_path,
    load_config,
    save_config,
    station_for_decode_camera,
)
from packrecorder.duplicate import is_duplicate_order
from packrecorder.ffmpeg_pipe_recorder import FFmpegPipeRecorder
from packrecorder.feedback_sound import FeedbackPlayer
from packrecorder.order_state import OrderStateMachine, ScanResult
from packrecorder.paths import build_output_path
from packrecorder.pip_composite import composite_pip_bgr
from packrecorder.retention import purge_old_day_folders
from packrecorder.scan_worker import ScanWorker
from packrecorder.shutdown_scheduler import compute_next_shutdown_at
from packrecorder.ui.countdown_dialog import ShutdownCountdownDialog
from packrecorder.ui.settings_dialog import SettingsDialog


def _parse_hhmm(s: str) -> time_cls:
    parts = s.replace(" ", "").split(":")
    try:
        h = int(parts[0]) if parts else 18
        m = int(parts[1]) if len(parts) > 1 else 0
    except ValueError:
        return time_cls(18, 0)
    return time_cls(h % 24, min(59, max(0, m)))


def _resolve_ffmpeg(cfg: AppConfig) -> Path:
    if cfg.ffmpeg_path.strip():
        p = Path(cfg.ffmpeg_path)
        if p.is_file():
            return p
    w = shutil.which("ffmpeg")
    if w:
        return Path(w)
    raise FileNotFoundError("Không tìm thấy ffmpeg. Thêm vào PATH hoặc chỉ đường dẫn trong Cài đặt.")


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Pack Recorder")
        self._config_path = default_config_path()
        self._config = load_config(self._config_path)
        self._next_shutdown_at: Optional[datetime] = None
        self._next_shutdown_ref: list[Optional[datetime]] = [None]
        self._refresh_next_shutdown()
        self._feedback = FeedbackPlayer(self._config)
        self._shutdown_countdown = False
        self._countdown_dialog: Optional[ShutdownCountdownDialog] = None

        self._workers: dict[int, ScanWorker] = {}
        self._pip_wh: dict[int, tuple[int, int]] = {}
        self._pip_last_frame: dict[int, bytes] = {}
        self._frame_w, self._frame_h, self._frame_fps = 640, 480, 15

        self._order_sm: dict[str, OrderStateMachine] = {}
        self._recorders: dict[str, FFmpegPipeRecorder | None] = {}
        self._binding_station_id: Optional[str] = None

        self._pip_timer = QTimer(self)
        self._pip_timer.timeout.connect(self._pip_tick)

        self._status = QStatusBar()
        self.setStatusBar(self._status)
        self._chip = QLabel("Chờ quét mã đơn")
        self._chip.setStyleSheet(
            "padding:6px 10px;border-radius:6px;background:#e8eaf6;color:#1a237e;"
        )
        self.statusBar().addPermanentWidget(self._chip)

        self._rebuild_order_machines()
        self._update_packer_message()

        m_settings = self.menuBar().addMenu("Tệp")
        act = QAction("Cài đặt", self)
        act.triggered.connect(self._open_settings)
        m_settings.addAction(act)

        self._bind_menu = QMenu("Gán máy quét (quét mã)", self)
        self._rebuild_bind_menu()
        self.menuBar().addMenu(self._bind_menu)

        self._purge_timer = QTimer(self)
        self._purge_timer.timeout.connect(self._run_retention)
        self._purge_timer.start(3 * 60 * 60 * 1000)
        QTimer.singleShot(0, self._run_retention)

        self._shutdown_timer = QTimer(self)
        self._shutdown_timer.timeout.connect(self._check_shutdown)
        self._shutdown_timer.start(15_000)

        self._restart_scan_workers()

    def _effective_stations(self) -> list[StationConfig]:
        if self._config.multi_camera_mode == "single":
            return [
                StationConfig(
                    "single",
                    self._config.packer_label,
                    self._config.camera_index,
                    self._config.camera_index,
                )
            ]
        if self._config.multi_camera_mode == "pip":
            return [
                StationConfig(
                    "pip",
                    self._config.packer_label,
                    self._config.pip_main_camera_index,
                    self._config.pip_decode_camera_index,
                )
            ]
        return list(self._config.stations)

    def _rebuild_order_machines(self) -> None:
        self._order_sm = {
            s.station_id: OrderStateMachine() for s in self._effective_stations()
        }
        self._recorders = {s.station_id: None for s in self._effective_stations()}

    def _rebuild_bind_menu(self) -> None:
        self._bind_menu.clear()
        if self._config.multi_camera_mode != "stations":
            self._bind_menu.setEnabled(False)
            return
        self._bind_menu.setEnabled(True)
        for s in self._config.stations:
            label = f"{s.packer_label} (decode cam {s.decode_camera_index})"
            act = QAction(label, self)
            act.triggered.connect(partial(self._start_bind, s.station_id, s.packer_label))
            self._bind_menu.addAction(act)

    def _start_bind(self, station_id: str, packer_label: str) -> None:
        self._binding_station_id = station_id
        self._status.showMessage(
            f"Quét bất kỳ mã hợp lệ để gán camera quét cho «{packer_label}»…",
            20000,
        )

    def _update_packer_message(self) -> None:
        if self._config.multi_camera_mode == "stations":
            names = ", ".join(s.packer_label for s in self._config.stations)
            self._status.showMessage(f"Quầy: {names}", 0)
        elif self._config.multi_camera_mode == "pip":
            self._status.showMessage(
                f"PIP — nhãn: {self._config.packer_label} "
                f"(chính cam {self._config.pip_main_camera_index}, "
                f"phụ cam {self._config.pip_sub_camera_index})",
                0,
            )
        else:
            self._status.showMessage(f"Nhãn gói: {self._config.packer_label}", 0)

    def _refresh_next_shutdown(self) -> None:
        if not self._config.shutdown_enabled:
            self._next_shutdown_at = None
            self._next_shutdown_ref[0] = None
            return
        t = _parse_hhmm(self._config.shutdown_time_hhmm)
        self._next_shutdown_at = compute_next_shutdown_at(t, datetime.now())
        self._next_shutdown_ref[0] = self._next_shutdown_at

    def _check_shutdown(self) -> None:
        if self._shutdown_countdown:
            return
        if not self._config.shutdown_enabled or self._next_shutdown_at is None:
            return
        if datetime.now() < self._next_shutdown_at:
            return
        self._begin_shutdown_sequence()

    def _begin_shutdown_sequence(self) -> None:
        self._stop_all_recording_for_shutdown()
        self._shutdown_countdown = True
        dlg = ShutdownCountdownDialog(self)
        dlg.set_next_shutdown_ref(self._next_shutdown_ref)
        dlg.scan_cancelled.connect(self._on_shutdown_scan_cancelled)
        dlg.shutdown_committed.connect(self._on_shutdown_commit)
        dlg.finished.connect(self._on_countdown_finished)
        self._countdown_dialog = dlg
        dlg.setModal(False)
        dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        dlg.start_countdown()
        dlg.show()

    def _on_countdown_finished(self) -> None:
        self._countdown_dialog = None
        self._shutdown_countdown = False

    def _on_shutdown_scan_cancelled(self) -> None:
        self._next_shutdown_at = self._next_shutdown_ref[0]
        self._shutdown_countdown = False
        self._status.showMessage("Đã hoãn tắt máy +1 giờ (quét mã).", 8000)

    def _on_shutdown_commit(self) -> None:
        self._cleanup_workers()

    def _run_retention(self) -> None:
        root = Path(self._config.video_root)
        if not root.is_dir():
            return
        purge_old_day_folders(root, 16, date.today())

    def _required_camera_indices(self) -> set[int]:
        if self._config.multi_camera_mode == "single":
            return {self._config.camera_index}
        if self._config.multi_camera_mode == "pip":
            return {
                self._config.pip_main_camera_index,
                self._config.pip_sub_camera_index,
            }
        cams: set[int] = set()
        for st in self._config.stations:
            cams.add(st.record_camera_index)
            cams.add(st.decode_camera_index)
        return cams

    def _camera_should_decode(self, cam: int) -> bool:
        if self._config.multi_camera_mode == "single":
            return True
        if self._config.multi_camera_mode == "pip":
            return cam == self._config.pip_decode_camera_index
        for st in self._config.stations:
            if st.decode_camera_index == cam:
                return True
        return False

    def _restart_scan_workers(self) -> None:
        self._pip_timer.stop()
        for w in self._workers.values():
            w.stop_worker()
        for w in self._workers.values():
            w.wait(5000)
        self._workers.clear()
        self._pip_last_frame.clear()

        is_sd = lambda: self._shutdown_countdown
        for cam in sorted(self._required_camera_indices()):
            decode = self._camera_should_decode(cam)
            w = ScanWorker(
                cam,
                decode_enabled=decode,
                is_shutdown_countdown=is_sd,
            )
            w.decoded.connect(self._on_decoded)
            w.frame_ready.connect(self._on_frame)
            w.camera_opened.connect(self._on_camera_opened_slot)
            w.start()
            self._workers[cam] = w

    def _on_camera_opened_slot(self, cam: int, w: int, h: int, fps: int) -> None:
        self._pip_wh[cam] = (w, h)
        fps = max(1, min(60, fps or 15))
        if self._config.multi_camera_mode == "single" and cam == self._config.camera_index:
            self._frame_w, self._frame_h, self._frame_fps = w, h, fps
        elif (
            self._config.multi_camera_mode == "pip"
            and cam == self._config.pip_main_camera_index
        ):
            self._frame_w, self._frame_h, self._frame_fps = w, h, fps

    def _station_by_id(self, sid: str) -> StationConfig | None:
        for s in self._effective_stations():
            if s.station_id == sid:
                return s
        return None

    def _reshape_bgr(self, cam: int, raw: bytes) -> np.ndarray | None:
        wh = self._pip_wh.get(cam)
        if not wh:
            return None
        w, h = wh
        need = w * h * 3
        if len(raw) != need:
            return None
        return np.frombuffer(raw, dtype=np.uint8).reshape((h, w, 3))

    def _pip_tick(self) -> None:
        if self._config.multi_camera_mode != "pip" or not self._recorders.get("pip"):
            return
        mc = self._config.pip_main_camera_index
        sc = self._config.pip_sub_camera_index
        b1 = self._pip_last_frame.get(mc)
        b2 = self._pip_last_frame.get(sc)
        if not b1 or not b2:
            return
        a = self._reshape_bgr(mc, b1)
        b = self._reshape_bgr(sc, b2)
        if a is None or b is None:
            return
        out = composite_pip_bgr(
            a,
            b,
            sub_max_width=self._config.pip_overlay_max_width,
            margin=self._config.pip_overlay_margin,
        )
        rec = self._recorders.get("pip")
        if rec:
            try:
                rec.write_frame(out.tobytes())
            except BrokenPipeError:
                pass

    def _on_frame(self, cam_idx: int, bgr: bytes) -> None:
        if self._config.multi_camera_mode == "pip":
            if self._recorders.get("pip"):
                self._pip_last_frame[cam_idx] = bgr
            return
        if self._config.multi_camera_mode == "single":
            if self._recorders.get("single") and cam_idx == self._config.camera_index:
                try:
                    self._recorders["single"].write_frame(bgr)
                except BrokenPipeError:
                    pass
            return
        for st in self._config.stations:
            if (
                self._recorders.get(st.station_id)
                and cam_idx == st.record_camera_index
            ):
                try:
                    self._recorders[st.station_id].write_frame(bgr)
                except BrokenPipeError:
                    pass

    def _refresh_worker_recording_flags(self) -> None:
        active_record_cams: set[int] = set()
        if self._config.multi_camera_mode == "pip":
            if self._recorders.get("pip"):
                active_record_cams.add(self._config.pip_main_camera_index)
                active_record_cams.add(self._config.pip_sub_camera_index)
        elif self._config.multi_camera_mode == "single":
            if self._recorders.get("single"):
                active_record_cams.add(self._config.camera_index)
        else:
            for st in self._config.stations:
                if self._recorders.get(st.station_id):
                    active_record_cams.add(st.record_camera_index)
        for cam, w in self._workers.items():
            w.set_recording(cam in active_record_cams)

    def _on_decoded(self, cam_idx: int, code: str) -> None:
        if self._shutdown_countdown and self._countdown_dialog is not None:
            self._countdown_dialog.on_barcode_during_countdown()
            return
        if self._binding_station_id is not None:
            self._apply_scan_bind(cam_idx)
            return

        if self._config.multi_camera_mode == "pip":
            self._handle_decode_pip(code)
            return
        if self._config.multi_camera_mode == "single":
            if cam_idx != self._config.camera_index:
                return
            self._handle_decode_station("single", code)
            return

        st = station_for_decode_camera(self._config.stations, cam_idx)
        if st is None:
            self._status.showMessage(
                f"Không có quầy nào dùng camera {cam_idx} để quét — vào Gán máy quét.",
                6000,
            )
            return
        self._handle_decode_station(st.station_id, code)

    def _apply_scan_bind(self, cam_idx: int) -> None:
        sid = self._binding_station_id
        self._binding_station_id = None
        if sid is None:
            return
        for i, x in enumerate(self._config.stations):
            if x.station_id == sid:
                self._config.stations[i] = replace(x, decode_camera_index=cam_idx)
                save_config(self._config_path, self._config)
                self._status.showMessage(
                    f"Đã gán camera {cam_idx} làm nguồn quét cho «{x.packer_label}».",
                    8000,
                )
                self._rebuild_bind_menu()
                self._restart_scan_workers()
                return

    def _handle_decode_pip(self, code: str) -> None:
        sm = self._order_sm["pip"]
        r = sm.on_scan(code, is_shutdown_countdown=False)
        if r.should_start_recording and r.new_active_order:
            self._begin_recording_pip(r.new_active_order, r.should_check_duplicate)
        if r.should_stop_recording:
            self._stop_recording_after_scan("pip", r)

    def _handle_decode_station(self, station_id: str, code: str) -> None:
        sm = self._order_sm.get(station_id)
        if sm is None:
            return
        r = sm.on_scan(code, is_shutdown_countdown=False)
        if r.should_start_recording and r.new_active_order:
            self._begin_recording_station(
                station_id, r.new_active_order, r.should_check_duplicate
            )
        if r.should_stop_recording:
            self._stop_recording_after_scan(station_id, r)

    def _begin_recording_station(
        self, station_id: str, order: str, *, check_dup: bool
    ) -> None:
        st = self._station_by_id(station_id)
        if st is None:
            return
        root = Path(self._config.video_root)
        root.mkdir(parents=True, exist_ok=True)
        dup = False
        if check_dup:
            dup = is_duplicate_order(root, order, date.today())
            if dup:
                self._status.showMessage(
                    f"[{st.packer_label}] Đơn {order} đã có video hôm nay — vẫn ghi thêm.",
                    8000,
                )
        try:
            ff = _resolve_ffmpeg(self._config)
        except FileNotFoundError as e:
            QMessageBox.warning(self, "Thiếu ffmpeg", str(e))
            self._order_sm[station_id] = OrderStateMachine()
            return
        w, h = self._pip_wh.get(st.record_camera_index, (self._frame_w, self._frame_h))
        fps = self._frame_fps
        out = build_output_path(
            root, order, st.packer_label, datetime.now()
        )
        rec = FFmpegPipeRecorder(ff, w, h, fps)
        try:
            rec.start(out)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Không bắt đầu ghi được", str(e))
            self._order_sm[station_id] = OrderStateMachine()
            return
        self._recorders[station_id] = rec
        self._refresh_worker_recording_flags()
        self._chip.setText(f"Đang ghi ({st.packer_label}): {order}")
        self._chip.setStyleSheet(
            "padding:6px 10px;border-radius:6px;background:#c8e6c9;color:#1b5e20;"
        )
        if dup:
            self._feedback.play_long()
        else:
            self._feedback.play_short()

    def _begin_recording_pip(self, order: str, *, check_dup: bool) -> None:
        root = Path(self._config.video_root)
        root.mkdir(parents=True, exist_ok=True)
        dup = False
        if check_dup:
            dup = is_duplicate_order(root, order, date.today())
            if dup:
                self._status.showMessage(
                    f"Đơn {order} đã có video hôm nay — vẫn ghi thêm.", 8000
                )
        try:
            ff = _resolve_ffmpeg(self._config)
        except FileNotFoundError as e:
            QMessageBox.warning(self, "Thiếu ffmpeg", str(e))
            self._order_sm["pip"] = OrderStateMachine()
            return
        out = build_output_path(
            root, order, self._config.packer_label, datetime.now()
        )
        rec = FFmpegPipeRecorder(ff, self._frame_w, self._frame_h, self._frame_fps)
        try:
            rec.start(out)
        except Exception as e:  # noqa: BLE001
            QMessageBox.warning(self, "Không bắt đầu ghi được", str(e))
            self._order_sm["pip"] = OrderStateMachine()
            return
        self._recorders["pip"] = rec
        self._pip_last_frame.clear()
        interval = max(16, int(1000 / max(1, self._frame_fps)))
        self._pip_timer.start(interval)
        self._refresh_worker_recording_flags()
        self._chip.setText(f"PIP đang ghi: {order}")
        self._chip.setStyleSheet(
            "padding:6px 10px;border-radius:6px;background:#c8e6c9;color:#1b5e20;"
        )
        if dup:
            self._feedback.play_long()
        else:
            self._feedback.play_short()

    def _stop_recording_for_station(self, station_id: str) -> None:
        if self._config.multi_camera_mode == "pip" and station_id == "pip":
            self._pip_timer.stop()
        rec = self._recorders.get(station_id)
        if rec:
            try:
                rec.stop()
            except Exception:
                pass
            self._recorders[station_id] = None
        self._refresh_worker_recording_flags()

    def _stop_all_recording_for_shutdown(self) -> None:
        self._pip_timer.stop()
        for sid in list(self._recorders.keys()):
            self._stop_recording_for_station(sid)
        self._chip.setText("Chờ quét mã đơn")
        self._chip.setStyleSheet(
            "padding:6px 10px;border-radius:6px;background:#e8eaf6;color:#1a237e;"
        )

    def _stop_recording_after_scan(self, station_id: str, r: ScanResult) -> None:
        rec = self._recorders.get(station_id)
        if rec:
            try:
                rec.stop()
            except Exception:
                pass
            self._recorders[station_id] = None
        if r.sound_immediate == "stop_double":
            self._feedback.play_double()
        if self._config.multi_camera_mode == "pip" and station_id == "pip":
            self._pip_timer.stop()
        self._refresh_worker_recording_flags()
        sm = self._order_sm.get(station_id)
        if sm is None:
            return
        nr = sm.notify_stop_confirmed()
        if nr.should_start_recording and nr.new_active_order:
            if self._config.multi_camera_mode == "pip":
                self._begin_recording_pip(
                    nr.new_active_order, check_dup=nr.should_check_duplicate
                )
            else:
                self._begin_recording_station(
                    station_id,
                    nr.new_active_order,
                    check_dup=nr.should_check_duplicate,
                )
        else:
            self._chip.setText("Chờ quét mã đơn")
            self._chip.setStyleSheet(
                "padding:6px 10px;border-radius:6px;background:#e8eaf6;color:#1a237e;"
            )

    def _pause_scan_workers(self) -> None:
        self._pip_timer.stop()
        for w in list(self._workers.values()):
            w.stop_worker()
        for w in list(self._workers.values()):
            w.wait(5000)
        self._workers.clear()

    def _open_settings(self) -> None:
        if any(r is not None for r in self._recorders.values()):
            QMessageBox.warning(
                self,
                "Đang ghi hình",
                "Vui lòng dừng ghi (quét lại cùng mã đơn hoặc đóng phiên) trước khi mở Cài đặt "
                "để xem trước camera.",
            )
            return
        self._pause_scan_workers()
        dlg = SettingsDialog(self._config, self)
        try:
            if dlg.exec():
                self._config = dlg.result_config()
                save_config(self._config_path, self._config)
                self._feedback.update_config(self._config)
                self._refresh_next_shutdown()
                self._rebuild_order_machines()
                self._rebuild_bind_menu()
                self._update_packer_message()
        finally:
            dlg.dispose_preview()
            self._restart_scan_workers()

    def _cleanup_workers(self) -> None:
        self._pip_timer.stop()
        for w in self._workers.values():
            w.stop_worker()
        for w in self._workers.values():
            w.wait(5000)
        self._workers.clear()

    def closeEvent(self, event) -> None:  # noqa: N802
        self._stop_all_recording_for_shutdown()
        self._cleanup_workers()
        super().closeEvent(event)
