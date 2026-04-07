"""Đọc mã vạch từ máy quét USB–Serial (cổng COM)."""

from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QThread, Signal

try:
    import serial
except ImportError:
    serial = None  # type: ignore[misc, assignment]


class SerialScanWorker(QThread):
    """Một luồng / một cổng COM; phát ra dòng đã quét (đã strip)."""

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

    def stop_worker(self) -> None:
        self._running = False

    def run(self) -> None:
        if serial is None:
            self.failed.emit(self._station_id, "Chưa cài pyserial (pip install pyserial).")
            return
        if not self._port:
            return
        try:
            ser = serial.Serial(self._port, self._baudrate, timeout=0.12)
        except Exception as e:  # noqa: BLE001
            self.failed.emit(self._station_id, f"Không mở được {self._port}: {e}")
            return
        last_text: Optional[str] = None
        last_mono = 0.0
        try:
            while self._running:
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
                self.line_decoded.emit(self._station_id, text)
        finally:
            try:
                ser.close()
            except Exception:
                pass
