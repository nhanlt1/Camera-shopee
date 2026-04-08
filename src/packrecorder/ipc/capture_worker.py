"""Tiến trình capture: RTSP/USB → full frame (cố định W×H) vào SharedMemory ring."""

from __future__ import annotations

import sys
import time
from multiprocessing import Lock
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Event
from queue import Full
from typing import Optional, Union

import numpy as np

from packrecorder.ipc.frame_ring import create_ring_shm, ndarray_slot
from packrecorder.opencv_video import (
    configure_opencv_logging,
    open_rtsp_capture,
    open_video_capture,
)
from packrecorder.record_resolution import apply_capture_resolution

import cv2

_PREVIEW_WARMUP_DISCARD_FRAMES = 0
_FALLBACK_CAPTURE_FPS = 30
_SYNC_WH_PROBE_READS = 12
_SYNC_WH_PROBE_READS_RTSP = 4


def mp_capture_worker_entry(
    camera_index: int,
    capture_source: Union[int, str],
    fallback_usb_index: Optional[int],
    capture_target_wh: Optional[tuple[int, int]],
    use_capture_resolution: bool,
    n_slots: int,
    feed_scanner_meta: bool,
    events_queue: Queue,
    meta_queue: Queue,
    stop_event: Event,
    latest_seq,
    latest_slot,
    latest_lock: Lock,
) -> None:
    """
    Top-level target cho Process(spawn).
    Tạo SharedMemory sau khi probe W×H; gửi ("ready", cam, shm.name, w, h, fps, n_slots).
    Child chỉ close SHM; parent gọi unlink sau khi join.
    """
    configure_opencv_logging()
    shm = None
    write_idx = 0
    seq = 0
    cap: Optional[cv2.VideoCapture] = None
    try:
        if isinstance(capture_source, str):
            try:
                cap = open_rtsp_capture(capture_source)
            except Exception:
                cap = None
            if cap is None:
                cap = cv2.VideoCapture()
        else:
            cap = open_video_capture(int(capture_source))
        if isinstance(capture_source, str) and (cap is None or not cap.isOpened()):
            try:
                if cap is not None:
                    cap.release()
            except Exception:
                pass
            if fallback_usb_index is not None:
                cap = open_video_capture(int(fallback_usb_index))
            else:
                events_queue.put(
                    (
                        "capture_failed",
                        camera_index,
                        "Không mở được RTSP (không có webcam dự phòng).",
                    )
                )
                return
        if cap is None or not cap.isOpened():
            events_queue.put(
                (
                    "capture_failed",
                    camera_index,
                    "Không mở được RTSP và webcam dự phòng (USB). Kiểm tra URL/mạng và chỉ số webcam.",
                )
            )
            return
        cw = 640
        ch = 480
        fps = _FALLBACK_CAPTURE_FPS
        try:
            if (
                isinstance(capture_source, int)
                and use_capture_resolution
                and capture_target_wh is not None
            ):
                tw, th = capture_target_wh
                cw, ch = apply_capture_resolution(cap, tw, th)
            else:
                cw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
                ch = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
        except Exception:
            cw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
            ch = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
        try:
            fps = int(cap.get(cv2.CAP_PROP_FPS)) or _FALLBACK_CAPTURE_FPS
        except Exception:
            fps = _FALLBACK_CAPTURE_FPS
        if fps <= 0 or fps > 60:
            fps = _FALLBACK_CAPTURE_FPS
        n_probe = (
            _SYNC_WH_PROBE_READS_RTSP
            if isinstance(capture_source, str)
            else _SYNC_WH_PROBE_READS
        )
        for _ in range(n_probe):
            ok, probe = cap.read()
            if (
                ok
                and probe is not None
                and getattr(probe, "ndim", 0) == 3
                and int(probe.shape[2]) >= 3
            ):
                ch, cw = int(probe.shape[0]), int(probe.shape[1])
                break
        shm = create_ring_shm(ch, cw, n_slots)
        events_queue.put(
            ("ready", camera_index, shm.name, cw, ch, fps, n_slots)
        )
        preview_discard_left = max(0, _PREVIEW_WARMUP_DISCARD_FRAMES)
        while not stop_event.is_set():
            if not cap.isOpened():
                time.sleep(0.2)
                continue
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.02)
                continue
            if getattr(frame, "ndim", 0) != 3 or int(frame.shape[2]) < 3:
                continue
            fh, fw = int(frame.shape[0]), int(frame.shape[1])
            if fh != ch or fw != cw:
                frame = cv2.resize(
                    frame, (cw, ch), interpolation=cv2.INTER_AREA
                )
            if preview_discard_left > 0:
                preview_discard_left -= 1
            dest = ndarray_slot(shm, write_idx, ch, cw)
            if frame.shape[0] == ch and frame.shape[1] == cw and frame.flags[
                "C_CONTIGUOUS"
            ]:
                dest[:] = frame
            else:
                try:
                    np.copyto(dest, np.ascontiguousarray(frame))
                except Exception:
                    continue
            seq += 1
            with latest_lock:
                latest_slot.value = write_idx
                latest_seq.value = seq
            if feed_scanner_meta:
                meta = (seq, write_idx, cw, ch)
                try:
                    meta_queue.put_nowait(meta)
                except Full:
                    try:
                        meta_queue.get_nowait()
                    except Exception:
                        pass
                    try:
                        meta_queue.put_nowait(meta)
                    except Exception:
                        pass
            write_idx = (write_idx + 1) % n_slots
    except Exception:
        try:
            import traceback

            events_queue.put(
                (
                    "capture_failed",
                    camera_index,
                    f"Lỗi capture: {traceback.format_exc()}",
                )
            )
        except Exception:
            pass
        try:
            from packrecorder.session_log import log_session_error

            log_session_error(
                f"mp_capture_worker (camera {camera_index}) lỗi.",
                exc_info=sys.exc_info(),
            )
        except Exception:
            pass
    finally:
        if cap is not None and cap.isOpened():
            try:
                cap.release()
            except Exception:
                pass
        if shm is not None:
            try:
                shm.close()
            except Exception:
                pass
