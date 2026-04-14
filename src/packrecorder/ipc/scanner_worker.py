"""Tiến trình quét mã: đọc slot từ SharedMemory + pyzbar."""

from __future__ import annotations

import time
import traceback

from multiprocessing import Lock
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Event
from queue import Empty
from typing import Optional

from packrecorder.barcode_decode import decode_barcodes_bgr
from packrecorder.ipc.frame_ring import attach_ring_shm, ndarray_slot
from packrecorder.opencv_video import configure_opencv_logging

import cv2
from packrecorder.record_roi import crop_bgr_frame, norm_to_pixels


def mp_scanner_worker_entry(
    camera_index: int,
    shm_name: str,
    width: int,
    height: int,
    n_slots: int,
    record_roi_norm: Optional[tuple[float, float, float, float]],
    decode_every_n_frames: int,
    decode_scan_scale: float,
    debounce_s: float,
    meta_queue: Queue,
    decode_queue: Queue,
    stop_event: Event,
    heartbeat_scanner,
    latest_seq,
    latest_lock: Lock,
    events_queue: Queue,
) -> None:
    configure_opencv_logging()
    shm = attach_ring_shm(shm_name)
    try:
        decode_every_n = max(1, int(decode_every_n_frames))
        scan_scale = max(0.25, min(1.0, float(decode_scan_scale)))
        last_code: Optional[str] = None
        last_emit_mono = 0.0
        seen_seq = 0
        while not stop_event.is_set():
            try:
                heartbeat_scanner.value = time.time()
            except Exception:
                pass
            try:
                seq, slot, fw, fh = meta_queue.get(timeout=0.25)
            except Empty:
                continue
            if seq <= seen_seq:
                continue
            with latest_lock:
                cur_latest = int(latest_seq.value)
            if seq != cur_latest:
                continue
            seen_seq = seq
            if (seq % decode_every_n) != 0:
                continue
            roi = record_roi_norm
            if roi is not None:
                px, py, pw, ph = norm_to_pixels(
                    roi[0], roi[1], roi[2], roi[3], fw, fh
                )
            else:
                px, py, pw, ph = 0, 0, fw, fh
            try:
                sl = int(slot) % n_slots
                full = ndarray_slot(shm, sl, fh, fw).copy()
            except Exception:
                continue
            work = crop_bgr_frame(full, px, py, pw, ph)
            try:
                scan_bgr = work
                if scan_scale < 0.999:
                    scan_bgr = cv2.resize(
                        work,
                        (
                            max(8, int(work.shape[1] * scan_scale)),
                            max(8, int(work.shape[0] * scan_scale)),
                        ),
                        interpolation=cv2.INTER_AREA,
                    )
                results = decode_barcodes_bgr(scan_bgr)
            except Exception:
                continue
            now = time.monotonic()
            for obj in results:
                try:
                    raw = obj.data.decode("utf-8", errors="replace").strip()
                except Exception:
                    continue
                if not raw:
                    continue
                if raw == last_code and (now - last_emit_mono) < debounce_s:
                    continue
                last_code = raw
                last_emit_mono = now
                try:
                    decode_queue.put((camera_index, raw))
                except Exception:
                    pass
    except Exception:
        try:
            events_queue.put(
                ("worker_error", camera_index, traceback.format_exc())
            )
        except Exception:
            pass
    finally:
        try:
            shm.close()
        except Exception:
            pass
