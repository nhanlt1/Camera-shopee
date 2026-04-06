from __future__ import annotations

import re
import shutil
from datetime import date, timedelta
from pathlib import Path

_DAY_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def purge_old_day_folders(root: Path, keep_days: int, today: date) -> list[Path]:
    if keep_days < 0:
        raise ValueError("keep_days must be >= 0")
    cutoff = today - timedelta(days=keep_days)
    removed: list[Path] = []
    if not root.is_dir():
        return removed
    for child in list(root.iterdir()):
        if not child.is_dir():
            continue
        if not _DAY_DIR.match(child.name):
            continue
        try:
            folder_date = date.fromisoformat(child.name)
        except ValueError:
            continue
        if folder_date < cutoff:
            shutil.rmtree(child, ignore_errors=True)
            removed.append(child)
    return removed
