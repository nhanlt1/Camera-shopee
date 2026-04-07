from __future__ import annotations

import sys
import time
from collections.abc import Callable
from typing import Optional, Union

from PySide6.QtCore import QThread, Signal

from packrecorder.barcode_decode import decode_barcodes_bgr
from packrecorder.record_roi import crop_bgr_frame, norm_to_pixels

# Nạp opencv_video trước cv2: module đặt OPENCV_LOG_LEVEL rồi mới import cv2.
from packrecorder.opencv_video import (
    configure_opencv_logging,
    open_rtsp_capture,
    open_video_capture,
)
from packrecorder.record_resolution import apply_capture_resolution
from packrecorder.session_log import log_session_error

import cv2

configure_opencv_logging()

# Không chờ nhiều khung trước khi gửi preview (tránh lên hình chậm ~0,3–0,7s).
# Có thể thấy 1 khung tối ngắn với MSMF; nếu cần ổn định hơn, tăng số này (ví dụ 2).
_PREVIEW_WARMUP_DISCARD_FRAMES = 0
# Nhiều webcam (MSMF) trả CAP_PROP_FPS = 0; 30 gần tốc độ thật hơn 15.
_FALLBACK_CAPTURE_FPS = 30
# Đọc tối đa bấy nhiêu khung sau mở để lấy W×H thật (buffer có thể khác cap.get).
# Giá trị lớn (vd. 90) có thể kéo dài nhiều giây với MSMF; vòng chính vẫn chỉnh lại W×H.
_SYNC_WH_PROBE_READS = 12
# RTSP: mỗi read có timeout (opencv_video); giảm số lần probe để không chờ quá lâu khi lỗi mạng.
_SYNC_WH_PROBE_READS_RTSP = 4


class ScanWorker(QThread):
    """OpenCV capture; optional pyzbar decode; frame_ready only while recording."""

    decoded = Signal(int, str)
    frame_ready = Signal(int, bytes)
    """BGR frame cho xem trước UI (không cần đang ghi)."""
    preview_ready = Signal(int, bytes)
    camera_opened = Signal(int, int, int, int)
    capture_failed = Signal(int, str)

    def __init__(
        self,
        camera_index: int,
        *,
        capture_source: Union[int, str, None] = None,
        fallback_usb_index: Optional[int] = None,
        debounce_s: float = 0.35,
        decode_enabled: bool = True,
        is_shutdown_countdown: Optional[Callable[[], bool]] = None,
        preview_fps: float = 8.0,
        capture_target_wh: Optional[tuple[int, int]] = None,
        decode_every_n_frames: int = 15,
        decode_scan_scale: float = 0.5,
        record_roi_norm: Optional[tuple[float, float, float, float]] = None,
    ) -> None:
        super().__init__()
        self._camera_index = camera_index
        self._capture_source: Union[int, str] = (
            capture_source if capture_source is not None else camera_index
        )
        self._fallback_usb_index = fallback_usb_index
        self._debounce_s = debounce_s
        self._decode_enabled = decode_enabled
        self._is_shutdown_countdown = is_shutdown_countdown or (lambda: False)
        self._preview_min_s = (1.0 / preview_fps) if preview_fps > 0 else 0.0
        self._last_preview_mono = 0.0
        self._running = True
        self._recording = False
        self._capture_target_wh = capture_target_wh
        self._decode_every_n = max(1, int(decode_every_n_frames))
        self._decode_scan_scale = max(0.25, min(1.0, float(decode_scan_scale)))
        self._record_roi_norm: Optional[tuple[float, float, float, float]] = (
            tuple(float(x) for x in record_roi_norm) if record_roi_norm is not None else None
        )

    @property
    def camera_index(self) -> int:
        return self._camera_index

    def stop_worker(self) -> None:
        self._running = False

    def set_recording(self, on: bool) -> None:
        self._recording = on

    def run(self) -> None:
        cap: Optional[cv2.VideoCapture] = None
        last_code: Optional[str] = None
        last_emit_mono = 0.0
        frame_i = 0
        try:
            configure_opencv_logging()
            # region agent log
            try:
                from packrecorder.debug_ndjson import dbg, dbg_safe_url

                dbg(
                    "H1",
                    "scan_worker.run.start",
                    "enter",
                    cam=self._camera_index,
                    is_rtsp=isinstance(self._capture_source, str),
                )
                if isinstance(self._capture_source, str):
                    dbg_safe_url("H1", "scan_worker.run.rtsp_url", self._capture_source)
            except Exception:
                pass
            # endregion agent log
            if isinstance(self._capture_source, str):
                cap = open_rtsp_capture(self._capture_source)
            else:
                cap = open_video_capture(int(self._capture_source))
            if (
                isinstance(self._capture_source, str)
                and (cap is None or not cap.isOpened())
                and self._fallback_usb_index is not None
            ):
                # region agent log
                try:
                    from packrecorder.debug_ndjson import dbg

                    dbg(
                        "H6",
                        "scan_worker.run.rtsp_fallback",
                        "rtsp_open_failed_fallback_to_usb",
                        cam=self._camera_index,
                        usb_index=int(self._fallback_usb_index),
                    )
                except Exception:
                    pass
                # endregion agent log
                self.capture_failed.emit(
                    self._camera_index,
                    f"Không mở được RTSP, tự chuyển sang webcam {int(self._fallback_usb_index)}.",
                )
                try:
                    if cap is not None:
                        cap.release()
                except Exception:
                    pass
                cap = open_video_capture(int(self._fallback_usb_index))
            # region agent log
            try:
                from packrecorder.debug_ndjson import dbg

                dbg(
                    "H1",
                    "scan_worker.run.after_open",
                    "capture opened",
                    opened=bool(cap is not None and cap.isOpened()),
                )
            except Exception:
                pass
            # endregion agent log
            preview_discard_left = 0
            cw = 640
            ch = 480
            fps = _FALLBACK_CAPTURE_FPS
            if cap.isOpened():
                try:
                    if (
                        isinstance(self._capture_source, int)
                        and self._capture_target_wh is not None
                    ):
                        tw, th = self._capture_target_wh
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
                start_w, start_h = cw, ch
                # Báo kích thước sớm cho UI/ghi (probe MSMF có thể chậm).
                self.camera_opened.emit(self._camera_index, cw, ch, fps)
                n_probe = (
                    _SYNC_WH_PROBE_READS_RTSP
                    if isinstance(self._capture_source, str)
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
                if cw != start_w or ch != start_h:
                    self.camera_opened.emit(self._camera_index, cw, ch, fps)
                preview_discard_left = max(0, _PREVIEW_WARMUP_DISCARD_FRAMES)
            while self._running:
                if not cap or not cap.isOpened():
                    time.sleep(0.2)
                    continue
                ok, frame = cap.read()
                if not ok:
                    time.sleep(0.02)
                    continue
                if getattr(frame, "ndim", 0) != 3 or int(frame.shape[2]) < 3:
                    continue
                fh, fw = int(frame.shape[0]), int(frame.shape[1])
                if fw != cw or fh != ch:
                    cw, ch = fw, fh
                    self.camera_opened.emit(self._camera_index, cw, ch, fps)
                if preview_discard_left > 0:
                    preview_discard_left -= 1
                roi = self._record_roi_norm
                if roi is not None:
                    px, py, pw, ph = norm_to_pixels(
                        roi[0], roi[1], roi[2], roi[3], fw, fh
                    )
                    work = crop_bgr_frame(frame, px, py, pw, ph)
                else:
                    work = frame
                if self._preview_min_s > 0 and preview_discard_left == 0:
                    now_prev = time.monotonic()
                    if now_prev - self._last_preview_mono >= self._preview_min_s:
                        self._last_preview_mono = now_prev
                        self.preview_ready.emit(self._camera_index, frame.tobytes())
                if self._recording:
                    self.frame_ready.emit(self._camera_index, work.tobytes())
                frame_i += 1
                if not self._decode_enabled:
                    continue
                if (frame_i % self._decode_every_n) != 0:
                    continue
                try:
                    scan_bgr = work
                    if self._decode_scan_scale < 0.999:
                        scan_bgr = cv2.resize(
                            work,
                            (
                                max(8, int(work.shape[1] * self._decode_scan_scale)),
                                max(8, int(work.shape[0] * self._decode_scan_scale)),
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
                    if self._is_shutdown_countdown():
                        self.decoded.emit(self._camera_index, raw)
                        last_code = None
                        continue
                    if raw == last_code and (now - last_emit_mono) < self._debounce_s:
                        continue
                    last_code = raw
                    last_emit_mono = now
                    self.decoded.emit(self._camera_index, raw)
        except Exception:
            # region agent log
            try:
                from packrecorder.debug_ndjson import dbg

                dbg(
                    "H1",
                    "scan_worker.run.exception",
                    "exception in run",
                    cam=self._camera_index,
                    is_rtsp=isinstance(self._capture_source, str),
                )
            except Exception:
                pass
            # endregion agent log
            log_session_error(
                f"ScanWorker (camera {self._camera_index}) lỗi trong run().",
                exc_info=sys.exc_info(),
            )
        finally:
            if cap is not None and cap.isOpened():
                cap.release()
