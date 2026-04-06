from __future__ import annotations

from abc import ABC, abstractmethod


class ScannerHostBeep(ABC):
    @abstractmethod
    def play_short(self) -> None:
        pass

    @abstractmethod
    def play_double(self, gap_ms: int) -> None:
        pass

    @abstractmethod
    def play_long(self) -> None:
        pass


class NullScannerHostBeep(ScannerHostBeep):
    def play_short(self) -> None:
        return

    def play_double(self, gap_ms: int) -> None:
        return

    def play_long(self) -> None:
        return
