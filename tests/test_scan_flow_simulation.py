"""
Mô phỏng **logic thuần** (máy trạng thái + chuẩn hoá + parse bytes giả).

**Không chứng minh** app thật sẽ quay video: không USB, không hidapi enumerate,
không FFmpeg, không MainWindow, không `_begin_recording_station`.

Mục đích: regression cho OrderStateMachine / debounce / parser — tránh lỗi logic.
Để kiểm tra môi trường HID: `tests/test_hid_environment_smoke.py`.

Đồng bộ với app:
- normalize_manual_order_text + OrderStateMachine.on_scan (same_scan_stops như COM/HID)
- Debounce khi chưa ghi (_SERIAL_SAME_CODE_DEBOUNCE_S trong main_window ≈ 0.45s)
- parse_hid_barcode_report (HID POS)
"""

from __future__ import annotations

import time

from packrecorder.hid_report_parse import parse_hid_barcode_report
from packrecorder.order_input import normalize_manual_order_text
from packrecorder.order_state import OrderStateMachine

# Giữ khớp packrecorder.ui.main_window._SERIAL_SAME_CODE_DEBOUNCE_S
_SERIAL_SAME_CODE_DEBOUNCE_S = 0.45


def test_simulate_hid_pos_report_to_start_recording_intent() -> None:
    """Giả lập một khung HID POS (ascii + null) → lần quét đầu yêu cầu bắt đầu ghi."""
    raw = bytes([1]) + b"SPX-2026-0001\x00"
    text = parse_hid_barcode_report(raw, "ascii_suffix_null")
    assert text == "SPX-2026-0001"

    t0 = 1000.0
    sm = OrderStateMachine()
    r = sm.on_scan(
        normalize_manual_order_text(text),
        is_shutdown_countdown=False,
        same_scan_stops_recording=True,
        now_mono=t0,
    )
    assert r.should_start_recording is True
    assert r.new_active_order == "SPX-2026-0001"


def test_simulate_com_style_line_to_same_flow() -> None:
    """Luồng chuỗi thuần (như COM) giống HID sau parse."""
    sm = OrderStateMachine()
    t0 = 500.0
    r1 = sm.on_scan(
        normalize_manual_order_text("ORD-99\r\n"),
        is_shutdown_countdown=False,
        same_scan_stops_recording=True,
        now_mono=t0,
    )
    assert r1.should_start_recording and r1.new_active_order == "ORD-99"
    sm.mark_recording_started(t0 + 0.01)
    r2 = sm.on_scan(
        "ORD-99",
        is_shutdown_countdown=False,
        same_scan_stops_recording=True,
        now_mono=t0 + 20.0,
    )
    assert r2.should_stop_recording is True


class _IdleDuplicateDebounceSimulator:
    """Mô phỏng nhánh «chưa ghi» trong _on_serial_decoded: bỏ qua trùng trong cửa sổ ngắn."""

    def __init__(self, debounce_s: float = _SERIAL_SAME_CODE_DEBOUNCE_S) -> None:
        self._debounce_s = debounce_s
        self._last: dict[str, tuple[str, float]] = {}

    def should_process(
        self, station_id: str, text: str, *, recorder_active: bool, now: float
    ) -> bool:
        if recorder_active:
            self._last[station_id] = (text, now)
            return True
        last = self._last.get(station_id)
        if (
            last
            and last[0] == text
            and (now - last[1]) < self._debounce_s
        ):
            return False
        self._last[station_id] = (text, now)
        return True


def test_simulate_idle_debounce_drops_duplicate_scan() -> None:
    sim = _IdleDuplicateDebounceSimulator()
    sid = "station-uuid-1"
    t0 = time.monotonic()
    assert sim.should_process(sid, "ABC", recorder_active=False, now=t0) is True
    assert (
        sim.should_process(sid, "ABC", recorder_active=False, now=t0 + 0.1) is False
    )
    assert sim.should_process(
        sid, "ABC", recorder_active=False, now=t0 + _SERIAL_SAME_CODE_DEBOUNCE_S + 0.1
    ) is True


def test_simulate_pipeline_callbacks_without_mainwindow() -> None:
    """
    End-to-end nhẹ: mỗi «lần quét» gọi callback; kiểm tra thứ tự start → dừng/chuyển → start đơn mới.
    Không dùng QApplication / MainWindow.
    """
    events: list[str] = []
    sm: OrderStateMachine | None = None

    def on_scan_line(raw_text: str) -> None:
        nonlocal sm
        if sm is None:
            sm = OrderStateMachine()
        text = normalize_manual_order_text(raw_text)
        if not text:
            return
        r = sm.on_scan(
            text,
            is_shutdown_countdown=False,
            same_scan_stops_recording=True,
            now_mono=time.monotonic(),
        )
        if r.should_start_recording and r.new_active_order:
            events.append(f"start:{r.new_active_order}")
        if r.should_stop_recording:
            events.append("stop_pending")
            c = sm.notify_stop_confirmed(now_mono=time.monotonic())
            if c.should_start_recording and c.new_active_order:
                events.append(f"start:{c.new_active_order}")

    on_scan_line(parse_hid_barcode_report(bytes([1]) + b"FIRST\x00", "ascii_suffix_null"))
    on_scan_line(
        parse_hid_barcode_report(bytes([1]) + b"SECOND\x00", "ascii_suffix_null")
    )
    assert events[0] == "start:FIRST"
    assert "stop_pending" in events
    assert events[-1] == "start:SECOND"
