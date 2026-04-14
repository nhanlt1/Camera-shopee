"""Backoff khi đọc khung camera thất bại liên tiếp (capture worker)."""

from __future__ import annotations

# Sau nhiều lần read() thất bại liên tiếp → báo capture_failed và thoát.
CAPTURE_MAX_CONSECUTIVE_READ_FAILS = 40


def read_fail_backoff_seconds(consecutive_fails: int) -> float:
    """Lần fail 1 → 1s, 2 → 2s, 3 → 4s, 4 → 8s, 5+ → 16s (trần)."""
    if consecutive_fails <= 0:
        return 0.0
    return min(16.0, float(2 ** min(consecutive_fails - 1, 4)))
