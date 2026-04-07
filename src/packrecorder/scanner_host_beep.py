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

    @abstractmethod
    def play_quad(self, gap_ms: int) -> None:
        """Bốn tiếng ngắn liên tiếp (báo trùng đơn)."""
        ...


class NullScannerHostBeep(ScannerHostBeep):
    def play_short(self) -> None:
        return

    def play_double(self, gap_ms: int) -> None:
        return

    def play_long(self) -> None:
        return

    def play_quad(self, gap_ms: int) -> None:
        return
