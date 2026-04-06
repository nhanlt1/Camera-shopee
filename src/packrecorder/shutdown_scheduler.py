from __future__ import annotations

from datetime import datetime, time, timedelta


def compute_next_shutdown_at(config_time: time, now: datetime) -> datetime:
    candidate = now.replace(
        hour=config_time.hour,
        minute=config_time.minute,
        second=0,
        microsecond=0,
    )
    if candidate <= now:
        candidate = candidate + timedelta(days=1)
    return candidate


def defer_one_hour(now: datetime) -> datetime:
    return now + timedelta(hours=1)
