from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

SoundEvent = Literal["start_short", "stop_double"]

# Máy quét (same_scan_stops_recording=True): trong khoảng này sau khi bắt đầu ghi, quét lại cùng mã + Enter bị bỏ qua.
SAME_ORDER_GRACE_S = 10.0


@dataclass
class ScanResult:
    should_start_recording: bool = False
    should_stop_recording: bool = False
    new_active_order: Optional[str] = None
    pending_switch_to: Optional[str] = None
    consume_for_shutdown_cancel: bool = False
    sound_immediate: Optional[SoundEvent] = None


class OrderStateMachine:
    IDLE = "idle"
    RECORDING = "recording"

    def __init__(self) -> None:
        self._mode = self.IDLE
        self._order: Optional[str] = None
        self._switch_target: Optional[str] = None
        self._recording_start_mono: Optional[float] = None

    def mark_recording_started(self, mono: float) -> None:
        """Gọi sau khi FFmpeg bắt đầu ghi thành công (dùng time.monotonic())."""
        self._recording_start_mono = mono

    def on_scan(
        self,
        code: str,
        *,
        is_shutdown_countdown: bool,
        same_scan_stops_recording: bool = True,
        now_mono: Optional[float] = None,
    ) -> ScanResult:
        code = code.strip()
        if is_shutdown_countdown:
            return ScanResult(consume_for_shutdown_cancel=True)
        if self._mode == self.IDLE:
            self._order = code
            self._mode = self.RECORDING
            return ScanResult(
                should_start_recording=True,
                new_active_order=code,
            )
        assert self._order is not None
        if code == self._order:
            if not same_scan_stops_recording:
                return ScanResult()
            if (
                self._recording_start_mono is not None
                and now_mono is not None
                and (now_mono - self._recording_start_mono) < SAME_ORDER_GRACE_S
            ):
                return ScanResult()
            return ScanResult(should_stop_recording=True, sound_immediate="stop_double")
        self._switch_target = code
        return ScanResult(should_stop_recording=True)

    def notify_stop_confirmed(self) -> ScanResult:
        self._recording_start_mono = None
        if self._switch_target:
            tgt = self._switch_target
            self._switch_target = None
            self._order = tgt
            return ScanResult(
                should_start_recording=True,
                new_active_order=tgt,
            )
        self._order = None
        self._mode = self.IDLE
        return ScanResult()
