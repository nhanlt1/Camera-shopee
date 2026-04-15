"""Đọc mã vạch từ máy quét HID POS (hidapi: VID/PID), không dùng COM."""

from __future__ import annotations

import queue
import threading
import time
from typing import Optional

from PySide6.QtCore import QThread, Signal

from packrecorder.hid_report_parse import parse_hid_barcode_report
from packrecorder.hid_scanner_discovery import HID_POS_USAGE_PAGE
from packrecorder.serial_scan_worker import (
    QUEUE_DROP_LOG_MIN_INTERVAL_S,
    SERIAL_SCAN_QUEUE_MAX,
    QueueItem,
    put_scan_line_drop_oldest,
)
from packrecorder.session_log import append_session_log

try:
    import hid as _hid
except ImportError:
    _hid = None  # type: ignore[misc, assignment]


def _path_for_hid_open(path: object) -> bytes:
    if path is None:
        return b""
    if isinstance(path, bytes):
        return path
    if isinstance(path, bytearray | memoryview):
        return bytes(path)
    return str(path).encode("utf-8", errors="surrogatepass")


def _open_hid_device(vid: int, pid: int) -> object:
    """Mở HID theo VID/PID.

    Trên Windows, thiết bị USB composite thường có nhiều interface; open(vid,pid) có thể
    trả «open failed». Ưu tiên mở đúng path từ hid.enumerate(), đặc biệt usage page POS (0x8C).
    """
    assert _hid is not None
    candidates: list[dict] = []
    try:
        raw = list(_hid.enumerate())
    except Exception:
        raw = []
    for d in raw:
        try:
            if int(d.get("vendor_id") or 0) != vid or int(d.get("product_id") or 0) != pid:
                continue
        except (TypeError, ValueError):
            continue
        if isinstance(d, dict):
            candidates.append(d)

    def _sort_key(item: dict) -> tuple[int, int]:
        up = int(item.get("usage_page") or 0)
        iface = int(item.get("interface_number") or 0)
        primary = 0 if up == HID_POS_USAGE_PAGE else 1
        return (primary, iface)

    candidates.sort(key=_sort_key)
    for d in candidates:
        path = d.get("path")
        pb = _path_for_hid_open(path)
        if not pb:
            continue
        dev = _hid.device()
        try:
            dev.open_path(pb)
            return dev
        except Exception:  # noqa: BLE001
            try:
                dev.close()
            except Exception:
                pass
            continue

    maker = getattr(_hid, "Device", None)
    if callable(maker):
        return maker(vid, pid)
    dev = _hid.device()
    dev.open(vid, pid)
    return dev


class HidPosScanWorker(QThread):
    """Một worker / một cặp VID:PID; luồng đọc HID tách, emit qua queue giới hạn."""

    line_decoded = Signal(str, str)
    failed = Signal(str, str)

    def __init__(
        self,
        station_id: str,
        vid_hex: str,
        pid_hex: str,
        *,
        profile: str = "ascii_suffix_null",
        debounce_s: float = 0.25,
    ) -> None:
        super().__init__()
        self._station_id = station_id
        self._vid_hex = (vid_hex or "").strip().upper()
        self._pid_hex = (pid_hex or "").strip().upper()
        self._profile = profile
        self._debounce_s = debounce_s
        self._running = True
        self._stop_event = threading.Event()
        self._device_lock = threading.Lock()
        self._device: object | None = None
        self._out_queue: queue.Queue[QueueItem] | None = None
        self._reader_thread: threading.Thread | None = None
        self._last_queue_drop_log_mono = 0.0

    def stop_worker(self) -> None:
        self._running = False
        self._stop_event.set()
        self._close_device_unlocked()

    def _close_device_unlocked(self) -> None:
        with self._device_lock:
            dev = self._device
            self._device = None
        if dev is not None:
            try:
                dev.close()
            except Exception:
                pass

    def _on_queue_drop(self) -> None:
        now = time.monotonic()
        if now - self._last_queue_drop_log_mono < QUEUE_DROP_LOG_MIN_INTERVAL_S:
            return
        self._last_queue_drop_log_mono = now
        append_session_log(
            "WARNING",
            f"Hàng đợi máy quét HID đầy (tối đa {SERIAL_SCAN_QUEUE_MAX}); đã bỏ mã cũ — [{self._station_id}]",
        )

    def _reader_loop(self) -> None:
        if _hid is None:
            return
        if len(self._vid_hex) != 4 or len(self._pid_hex) != 4:
            return
        try:
            vid = int(self._vid_hex, 16)
            pid = int(self._pid_hex, 16)
        except ValueError:
            self.failed.emit(
                self._station_id,
                f"VID/PID không hợp lệ: {self._vid_hex}:{self._pid_hex}",
            )
            return
        try:
            dev = _open_hid_device(vid, pid)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(
                self._station_id,
                f"Không mở được HID {self._vid_hex}:{self._pid_hex}: {e}",
            )
            return
        if hasattr(dev, "set_nonblocking"):
            try:
                dev.set_nonblocking(0)
            except Exception:
                pass
        with self._device_lock:
            self._device = dev
        last_text: Optional[str] = None
        last_mono = 0.0
        q = self._out_queue
        assert q is not None
        try:
            while not self._stop_event.is_set():
                try:
                    raw = dev.read(64, 200)
                except Exception as e:  # noqa: BLE001
                    self.failed.emit(self._station_id, str(e))
                    break
                if not raw:
                    continue
                data = raw if isinstance(raw, (bytes, bytearray)) else bytes(raw)
                try:
                    text = parse_hid_barcode_report(data, self._profile)
                except ValueError as e:
                    self.failed.emit(self._station_id, str(e))
                    break
                if not text:
                    continue
                now = time.monotonic()
                if text == last_text and (now - last_mono) < self._debounce_s:
                    continue
                last_text = text
                last_mono = now
                put_scan_line_drop_oldest(
                    q,
                    self._station_id,
                    text,
                    on_drop=self._on_queue_drop,
                )
        finally:
            self._close_device_unlocked()

    def run(self) -> None:
        if _hid is None:
            self.failed.emit(
                self._station_id,
                "Chưa import được HID (pip install 'hidapi>=0.14' hoặc pip install -e .).",
            )
            return
        if len(self._vid_hex) != 4 or len(self._pid_hex) != 4:
            self.failed.emit(
                self._station_id,
                "Cần VID và PID dạng HEX 4 ký tự (ví dụ 0C2E và 0B61).",
            )
            return
        self._out_queue = queue.Queue(maxsize=SERIAL_SCAN_QUEUE_MAX)
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name=f"HidReader-{self._station_id}",
            daemon=True,
        )
        self._reader_thread.start()
        q = self._out_queue
        assert q is not None
        try:
            while self._running:
                try:
                    item = q.get(timeout=0.25)
                except queue.Empty:
                    continue
                if item is None:
                    break
                station_id, text = item
                self.line_decoded.emit(station_id, text)
            while True:
                try:
                    item = q.get_nowait()
                except queue.Empty:
                    break
                if item is None:
                    break
                station_id, text = item
                self.line_decoded.emit(station_id, text)
        finally:
            self._stop_event.set()
            self._close_device_unlocked()
            if self._reader_thread is not None:
                self._reader_thread.join(timeout=3.0)
