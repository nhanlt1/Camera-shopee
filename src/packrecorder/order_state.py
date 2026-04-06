from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

SoundEvent = Literal["start_short", "stop_double", "start_long"]


@dataclass
class ScanResult:
    should_start_recording: bool = False
    should_stop_recording: bool = False
    should_check_duplicate: bool = False
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

    def on_scan(self, code: str, *, is_shutdown_countdown: bool) -> ScanResult:
        code = code.strip()
        if is_shutdown_countdown:
            return ScanResult(consume_for_shutdown_cancel=True)
        if self._mode == self.IDLE:
            self._order = code
            self._mode = self.RECORDING
            return ScanResult(
                should_start_recording=True,
                should_check_duplicate=True,
                new_active_order=code,
            )
        assert self._order is not None
        if code == self._order:
            return ScanResult(should_stop_recording=True, sound_immediate="stop_double")
        self._switch_target = code
        return ScanResult(should_stop_recording=True)

    def notify_stop_confirmed(self) -> ScanResult:
        if self._switch_target:
            tgt = self._switch_target
            self._switch_target = None
            self._order = tgt
            return ScanResult(
                should_start_recording=True,
                should_check_duplicate=True,
                new_active_order=tgt,
            )
        self._order = None
        self._mode = self.IDLE
        return ScanResult()

    @staticmethod
    def sound_for_start(*, duplicate: bool) -> SoundEvent:
        return "start_long" if duplicate else "start_short"
