"""Tiến trình writer: đọc khung từ SharedMemory → burn-in → FFmpeg (rawvideo BGR)."""

from __future__ import annotations

import time
from datetime import datetime
from multiprocessing.queues import Queue
from multiprocessing.synchronize import Event, Lock
from pathlib import Path
from typing import Any, Optional

import numpy as np

from packrecorder.ffmpeg_pipe_recorder import FFmpegPipeRecorder
from packrecorder.ipc.frame_ring import attach_ring_shm, ndarray_slot
from packrecorder.record_roi import crop_bgr_frame, norm_to_pixels
from packrecorder.video_overlay import burn_in_recording_info_bgr


def _copy_latest_roi_bgr(
    shm: Any,
    *,
    full_w: int,
    full_h: int,
    n_slots: int,
    latest_seq,
    latest_slot,
    latest_lock: Lock,
    roi_norm: Optional[tuple[float, float, float, float]],
    need: int,
) -> Optional[bytes]:
    with latest_lock:
        slot = int(latest_slot.value)
        seq = int(latest_seq.value)
    _ = seq
    if seq <= 0:
        return None
    sl = slot % n_slots
    try:
        ful = ndarray_slot(shm, sl, full_h, full_w).copy()
    except Exception:
        return None
    if roi_norm is None:
        raw = np.ascontiguousarray(ful).tobytes()
        return raw if len(raw) == need else None
    px, py, pw, ph = norm_to_pixels(
        roi_norm[0], roi_norm[1], roi_norm[2], roi_norm[3], full_w, full_h, even=True
    )
    crop = crop_bgr_frame(ful, px, py, pw, ph)
    raw = crop.tobytes()
    return raw if len(raw) == need else None


def mp_encode_writer_entry(
    stop_ev: Event,
    ack_q: Queue,
    shm_name: str,
    full_w: int,
    full_h: int,
    n_slots: int,
    latest_seq,
    latest_slot,
    latest_lock: Lock,
    roi_norm: Optional[tuple[float, float, float, float]],
    order: str,
    packer: str,
    started_at_iso: str,
    ffmpeg_exe: str,
    output_path: str,
    fps: int,
    codec_pref: str,
    bitrate_kbps: int,
    h264_crf: int,
    record_w: int,
    record_h: int,
) -> None:
    """spawn target: ghi MP4 cho tới khi stop_ev."""
    started_at = datetime.fromisoformat(started_at_iso)
    need = int(record_w) * int(record_h) * 3
    fps_out = max(1, min(60, int(fps)))
    interval = 1.0 / fps_out
    max_burst = 10
    rec: Optional[FFmpegPipeRecorder] = None
    shm = None
    try:
        shm = attach_ring_shm(shm_name)
        rec = FFmpegPipeRecorder(
            Path(ffmpeg_exe),
            record_w,
            record_h,
            fps_out,
            codec_preference=codec_pref,
            bitrate_kbps=bitrate_kbps,
            h264_crf=h264_crf,
        )
        rec.start(Path(output_path))
    except Exception as e:  # noqa: BLE001
        try:
            ack_q.put(("err", str(e)))
        except Exception:
            pass
        if shm is not None:
            try:
                shm.close()
            except Exception:
                pass
        return
    try:
        ack_q.put(("ok",))
    except Exception:
        pass
    nxt = time.monotonic()
    last_raw: Optional[bytes] = None
    try:
        while not stop_ev.is_set():
            now = time.monotonic()
            burst = 0
            while now >= nxt and burst < max_burst and not stop_ev.is_set():
                raw = _copy_latest_roi_bgr(
                    shm,
                    full_w=full_w,
                    full_h=full_h,
                    n_slots=n_slots,
                    latest_seq=latest_seq,
                    latest_slot=latest_slot,
                    latest_lock=latest_lock,
                    roi_norm=roi_norm,
                    need=need,
                )
                if raw is not None:
                    last_raw = raw
                if last_raw is not None and len(last_raw) == need:
                    frame_arr = np.frombuffer(
                        memoryview(last_raw), dtype=np.uint8
                    ).reshape((record_h, record_w, 3))
                else:
                    frame_arr = np.zeros((record_h, record_w, 3), dtype=np.uint8)
                wall_now = datetime.now()
                out = burn_in_recording_info_bgr(
                    frame_arr,
                    order=order,
                    packer=packer,
                    wall_now=wall_now,
                    started_at=started_at,
                )
                try:
                    rec.write_frame(out.tobytes())
                except BrokenPipeError:
                    break
                nxt += interval
                burst += 1
                now = time.monotonic()
            if stop_ev.is_set():
                break
            sleep_s = nxt - time.monotonic()
            if sleep_s > 0:
                time.sleep(min(sleep_s, 0.2))
    finally:
        if rec is not None:
            try:
                rec.stop()
            except Exception:
                pass
        if shm is not None:
            try:
                shm.close()
            except Exception:
                pass
