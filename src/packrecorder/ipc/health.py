"""Helpers for multiprocessing worker liveness (wall-clock heartbeats)."""

from __future__ import annotations


def is_stale(last_wall_time: float, now_wall: float, stale_after_s: float) -> bool:
    """
    True if last_wall_time is too old compared to now_wall.
    If stale_after_s <= 0, watchdog is disabled (never stale).
    If last_wall_time <= 0, treat as «chưa có nhịp» — not stale (tránh báo động lúc khởi động).
    """
    if stale_after_s <= 0:
        return False
    if last_wall_time <= 0:
        return False
    return (now_wall - last_wall_time) > stale_after_s
