from __future__ import annotations

from datetime import date
from pathlib import Path

from packrecorder.paths import sanitize_order_id


def is_duplicate_order(root: Path, order_id_raw: str, today: date) -> bool:
    oid = sanitize_order_id(order_id_raw)
    day_dir = root / today.isoformat()
    if not day_dir.is_dir():
        return False
    pattern = f"{oid}_*.mp4"
    return any(day_dir.glob(pattern))
