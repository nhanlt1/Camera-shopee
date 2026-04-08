"""Đọc mã vạch từ máy quét USB–Serial (cổng COM)."""

from __future__ import annotations

import queue
import threading
import time
from typing import TYPE_CHECKING, Callable, Optional, Tuple, Union

if TYPE_CHECKING:
    from serial import Serial as SerialHandle

from PySide6.QtCore import QThread, Signal

try:
    import serial
except ImportError:
    serial = None  # type: ignore[misc, assignment]

from packrecorder.session_log import append_session_log

# Hàng đợi giữa luồng đọc COM và luồng emit (QThread); giới hạn số sự kiện chờ UI.
SERIAL_SCAN_QUEUE_MAX = 32
# Không spam run_errors khi queue đầy liên tục.
QUEUE_DROP_LOG_MIN_INTERVAL_S = 5.0

QueueItem = Union[Tuple[str, str], None]


def put_scan_line_drop_oldest(
    q: "queue.Queue[QueueItem]",
    station_id: str,
    text: str,
    *,
    on_drop: Callable[[], None] | None = None,
) -> None:
    """Đưa (station_id, text) vào queue; nếu đầy thì bỏ phần tử cũ nhất rồi put lại."""
    item: Tuple[str, str] = (station_id, text)
    try:
        q.put_nowait(item)
    except queue.Full:
        try:
            q.get_nowait()
        except queue.Empty:
            pass
        if on_drop is not None:
            on_drop()
        try:
            q.put_nowait(item)
        except queue.Full:
            pass


class SerialScanWorker(QThread):
    """Một worker / một cổng COM; luồng đọc serial tách, emit qua queue giới hạn."""

    line_decoded = Signal(str, str)
    failed = Signal(str, str)

    def __init__(
        self,
        station_id: str,
        port: str,
        *,
        baudrate: int = 9600,
        debounce_s: float = 0.25,
    ) -> None:
        super().__init__()
        self._station_id = station_id
        self._port = port.strip()
        self._baudrate = baudrate
        self._debounce_s = debounce_s
        self._running = True
        self._stop_event = threading.Event()
        self._serial_lock = threading.Lock()
        self._serial_port: Optional["SerialHandle"] = None
        self._out_queue: queue.Queue[QueueItem] | None = None
        self._reader_thread: threading.Thread | None = None
        self._last_queue_drop_log_mono = 0.0

    def stop_worker(self) -> None:
        self._running = False
        self._stop_event.set()
        self._close_serial_unlocked()

    def _close_serial_unlocked(self) -> None:
        with self._serial_lock:
            ser = self._serial_port
            if ser is not None:
                try:
                    ser.close()
                except Exception:
                    pass

    def _on_queue_drop(self) -> None:
        now = time.monotonic()
        if now - self._last_queue_drop_log_mono < QUEUE_DROP_LOG_MIN_INTERVAL_S:
            return
        self._last_queue_drop_log_mono = now
        append_session_log(
            "WARNING",
            f"Hàng đợi máy quét COM đầy (tối đa {SERIAL_SCAN_QUEUE_MAX}); đã bỏ mã cũ — [{self._station_id}]",
        )

    def _reader_loop(self) -> None:
        if serial is None:
            return
        if not self._port:
            return
        try:
            ser = serial.Serial(self._port, self._baudrate, timeout=0.12)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(self._station_id, f"Không mở được {self._port}: {e}")
            return
        with self._serial_lock:
            self._serial_port = ser
        last_text: Optional[str] = None
        last_mono = 0.0
        q = self._out_queue
        assert q is not None
        try:
            while not self._stop_event.is_set():
                try:
                    raw = ser.readline()
                except serial.SerialException as e:
                    self.failed.emit(self._station_id, str(e))
                    break
                if not raw:
                    continue
                text = raw.decode("utf-8", errors="replace").strip()
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
            with self._serial_lock:
                self._serial_port = None
            try:
                ser.close()
            except Exception:
                pass

    def run(self) -> None:
        if serial is None:
            self.failed.emit(
                self._station_id,
                "Chưa cài pyserial (pip install pyserial).",
            )
            return
        if not self._port:
            return
        self._out_queue = queue.Queue(maxsize=SERIAL_SCAN_QUEUE_MAX)
        self._reader_thread = threading.Thread(
            target=self._reader_loop,
            name=f"SerialReader-{self._station_id}",
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
            # Dừng: lấy nốt mã còn trong queue (không chờ thêm).
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
            self._close_serial_unlocked()
            if self._reader_thread is not None:
                self._reader_thread.join(timeout=3.0)
