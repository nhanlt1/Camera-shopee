from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtMultimedia import QSoundEffect

from packrecorder.config import AppConfig
from packrecorder.scanner_host_beep import NullScannerHostBeep, ScannerHostBeep


class FeedbackPlayer:
    """Âm báo: 1 tiếng = bắt đầu ghi; 2 tiếng = dừng ghi; 4 tiếng = trùng đơn."""

    def __init__(self, cfg: AppConfig, host_beep: ScannerHostBeep | None = None) -> None:
        self._cfg = cfg
        self._host = host_beep or NullScannerHostBeep()
        self._short: QSoundEffect | None = None
        self._long: QSoundEffect | None = None
        self._double_timer: QTimer | None = None

    def _ensure_sound_effects(self) -> None:
        if self._short is not None:
            return
        self._short = QSoundEffect()
        self._long = QSoundEffect()
        self._apply_sources()

    def update_config(self, cfg: AppConfig) -> None:
        self._cfg = cfg
        if self._short is not None:
            self._apply_sources()

    def _apply_sources(self) -> None:
        if self._short is None or self._long is None:
            return
        for eff, path_str in (
            (self._short, self._cfg.wav_short_path),
            (self._long, self._cfg.wav_long_path),
        ):
            if path_str and Path(path_str).is_file():
                eff.setSource(QUrl.fromLocalFile(str(Path(path_str).resolve())))
            else:
                eff.setSource(QUrl())

    def _use_host(self) -> bool:
        return (
            self._cfg.sound_enabled
            and self._cfg.sound_mode == "scanner_host"
        )

    def play_short(self) -> None:
        if not self._cfg.sound_enabled:
            return
        self._ensure_sound_effects()
        if self._use_host():
            self._host.play_short()
            return
        if self._short.source().isValid():
            self._short.play()
        elif sys.platform == "win32":
            import winsound

            winsound.Beep(880, self._cfg.beep_short_ms)
        else:
            print("\a", end="", flush=True)

    def play_double(self) -> None:
        if not self._cfg.sound_enabled:
            return
        self._ensure_sound_effects()
        if self._use_host():
            self._host.play_double(self._cfg.beep_gap_ms)
            return
        self.play_short()
        gap = max(10, self._cfg.beep_gap_ms)
        QTimer.singleShot(gap, self.play_short)

    def play_quad(self) -> None:
        """Bốn tiếng ngắn liên tiếp — đơn đã có video hôm nay (trùng đơn)."""
        if not self._cfg.sound_enabled:
            return
        self._ensure_sound_effects()
        if self._use_host():
            self._host.play_quad(self._cfg.beep_gap_ms)
            return
        gap = max(10, self._cfg.beep_gap_ms)
        self._schedule_short_burst(4, gap)

    def _schedule_short_burst(self, count: int, gap_ms: int) -> None:
        if count <= 0:
            return
        self.play_short()
        if count > 1:
            QTimer.singleShot(
                gap_ms,
                lambda: self._schedule_short_burst(count - 1, gap_ms),
            )

    def play_long(self) -> None:
        if not self._cfg.sound_enabled:
            return
        self._ensure_sound_effects()
        if self._use_host():
            self._host.play_long()
            return
        if self._long.source().isValid():
            self._long.play()
        elif sys.platform == "win32":
            import winsound

            winsound.Beep(440, self._cfg.beep_long_ms)
        else:
            print("\a", end="", flush=True)
