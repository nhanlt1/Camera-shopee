"""Điều phối Process capture + scanner và SharedMemory (tiến trình chính attach)."""

from __future__ import annotations

import multiprocessing as mp
import sys
from multiprocessing.queues import Queue
from queue import Empty
from typing import Any, Optional

import numpy as np

from packrecorder.ipc.capture_worker import mp_capture_worker_entry
from packrecorder.ipc.frame_ring import attach_ring_shm, close_unlink, ndarray_slot
from packrecorder.ipc.scanner_worker import mp_scanner_worker_entry


class MpCameraPipeline:
    def __init__(
        self,
        *,
        camera_index: int,
        capture_source: int | str,
        fallback_usb_index: Optional[int],
        capture_target_wh: Optional[tuple[int, int]],
        use_capture_resolution: bool,
        decode_enabled: bool,
        record_roi_norm: Optional[tuple[float, float, float, float]],
        decode_every_n_frames: int,
        decode_scan_scale: float,
        debounce_s: float,
        n_slots: int = 3,
    ) -> None:
        self.camera_index = int(camera_index)
        self._capture_source = capture_source
        self._fallback_usb = fallback_usb_index
        self._capture_target_wh = capture_target_wh
        self._use_cap_resolution = use_capture_resolution
        self._decode_enabled = decode_enabled
        self._record_roi_norm = record_roi_norm
        self._decode_every_n = decode_every_n_frames
        self._decode_scan_scale = decode_scan_scale
        self._debounce_s = debounce_s
        self._n_slots = max(2, int(n_slots))

        self._ctx = mp.get_context("spawn")
        self._events_q: Queue = self._ctx.Queue()
        self._meta_q: Queue = self._ctx.Queue(maxsize=16)
        self._decode_q: Queue = self._ctx.Queue()
        self._stop = self._ctx.Event()
        self._latest_seq = self._ctx.Value("Q", 0)
        self._latest_slot = self._ctx.Value("i", 0)
        self._latest_lock = self._ctx.Lock()

        self._cap_proc: Optional[mp.Process] = None
        self._scan_proc: Optional[mp.Process] = None
        self._shm: Any = None
        self._shm_w = 0
        self._shm_h = 0
        self._shm_name: Optional[str] = None
        self._fps = 30
        self._scanner_started = False
        self._running = False

    @property
    def context(self) -> mp.context.BaseContext:
        return self._ctx

    def attach_params_for_writer(
        self,
    ) -> Optional[tuple[str, int, int, int, Any, Any, Any]]:
        """shm_name, full_w, full_h, n_slots, latest_seq, latest_slot, latest_lock."""
        if self._shm is None or self._shm_name is None:
            return None
        return (
            self._shm_name,
            self._shm_w,
            self._shm_h,
            self._n_slots,
            self._latest_seq,
            self._latest_slot,
            self._latest_lock,
        )

    def start(self) -> None:
        if self._running:
            return
        self._stop.clear()
        self._scanner_started = False
        self._cap_proc = self._ctx.Process(
            target=mp_capture_worker_entry,
            args=(
                self.camera_index,
                self._capture_source,
                self._fallback_usb,
                self._capture_target_wh,
                self._use_cap_resolution,
                self._n_slots,
                self._decode_enabled,
                self._events_q,
                self._meta_q,
                self._stop,
                self._latest_seq,
                self._latest_slot,
                self._latest_lock,
            ),
            daemon=False,
        )
        self._cap_proc.start()
        self._running = True

    def _attach_and_start_scanner(self, shm_name: str, w: int, h: int) -> None:
        if self._shm is not None:
            try:
                self._shm.close()
            except Exception:
                pass
            try:
                self._shm.unlink()
            except FileNotFoundError:
                pass
            self._shm = None
        self._shm = attach_ring_shm(shm_name)
        self._shm_name = shm_name
        self._shm_w = int(w)
        self._shm_h = int(h)
        if not self._decode_enabled:
            self._scanner_started = True
            return
        if self._scan_proc is not None and self._scan_proc.is_alive():
            return
        self._scan_proc = self._ctx.Process(
            target=mp_scanner_worker_entry,
            args=(
                self.camera_index,
                shm_name,
                w,
                h,
                self._n_slots,
                self._record_roi_norm,
                self._decode_every_n,
                self._decode_scan_scale,
                self._debounce_s,
                self._meta_q,
                self._decode_q,
                self._stop,
            ),
            daemon=False,
        )
        self._scan_proc.start()
        self._scanner_started = True

    def pump_events(self) -> list[tuple[Any, ...]]:
        out: list[tuple[Any, ...]] = []
        while True:
            try:
                msg = self._events_q.get_nowait()
            except Empty:
                break
            out.append(msg)
            if msg and len(msg) > 0 and msg[0] == "ready":
                try:
                    if len(msg) < 7:
                        raise ValueError(f"ready tuple length {len(msg)}")
                    _tag, cam, name, w, h, fps, n_sl = msg[:7]
                    self._fps = int(fps)
                    self._n_slots = int(n_sl)
                    self._attach_and_start_scanner(str(name), int(w), int(h))
                except Exception:
                    try:
                        from packrecorder.session_log import log_session_error

                        log_session_error(
                            f"MpCameraPipeline.pump_events: xử lý ready thất bại: {msg!r}",
                            exc_info=sys.exc_info(),
                        )
                    except Exception:
                        pass
        return out

    def pump_decodes(self) -> list[tuple[int, str]]:
        items: list[tuple[int, str]] = []
        while True:
            try:
                pair = self._decode_q.get_nowait()
            except Empty:
                break
            if (
                isinstance(pair, tuple)
                and len(pair) == 2
                and isinstance(pair[1], str)
            ):
                items.append((int(pair[0]), pair[1]))
        return items

    @property
    def is_ready(self) -> bool:
        return self._shm is not None and self._shm_w > 0 and self._shm_h > 0

    @property
    def frame_wh(self) -> tuple[int, int]:
        return (self._shm_w, self._shm_h)

    @property
    def frame_fps(self) -> int:
        return self._fps

    def copy_latest_full_bgr_bytes(self) -> Optional[bytes]:
        if not self.is_ready or self._shm is None:
            return None
        with self._latest_lock:
            slot = int(self._latest_slot.value)
            seq = int(self._latest_seq.value)
        if seq <= 0:
            return None
        slot = slot % self._n_slots
        try:
            view = ndarray_slot(
                self._shm, slot, self._shm_h, self._shm_w
            ).copy()
        except Exception:
            return None
        return view.tobytes()

    def copy_latest_roi_bgr_bytes(
        self,
        roi_norm: Optional[tuple[float, float, float, float]],
    ) -> Optional[bytes]:
        raw = self.copy_latest_full_bgr_bytes()
        if raw is None:
            return None
        w, h = self._shm_w, self._shm_h
        arr = np.frombuffer(raw, dtype=np.uint8).reshape((h, w, 3))
        if roi_norm is None:
            return raw
        from packrecorder.record_roi import crop_bgr_frame, norm_to_pixels

        px, py, pw, ph = norm_to_pixels(
            roi_norm[0], roi_norm[1], roi_norm[2], roi_norm[3], w, h, even=True
        )
        return crop_bgr_frame(arr, px, py, pw, ph).tobytes()

    def stop(self) -> None:
        self._running = False
        self._stop.set()
        if self._scan_proc is not None:
            self._scan_proc.join(timeout=4.0)
            if self._scan_proc.is_alive():
                self._scan_proc.terminate()
                self._scan_proc.join(timeout=2.0)
            self._scan_proc = None
        if self._cap_proc is not None:
            self._cap_proc.join(timeout=6.0)
            if self._cap_proc.is_alive():
                self._cap_proc.terminate()
                self._cap_proc.join(timeout=2.0)
            self._cap_proc = None
        close_unlink(self._shm)
        self._shm = None
        self._shm_name = None
        self._shm_w = self._shm_h = 0
        self._scanner_started = False
        try:
            while True:
                self._events_q.get_nowait()
        except Empty:
            pass
        try:
            while True:
                self._meta_q.get_nowait()
        except Empty:
            pass
        try:
            while True:
                self._decode_q.get_nowait()
        except Empty:
            pass
