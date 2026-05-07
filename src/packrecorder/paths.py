from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_order_id(raw: str) -> str:
    s = raw.strip()
    s = _INVALID.sub("-", s)
    s = s.replace("_", "-")
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "ORDER"


def sanitize_packer_label(raw: str) -> str:
    s = raw.strip()
    s = _INVALID.sub("-", s)
    s = s.replace("_", "-")
    s = s.replace(" ", "-")
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "Máy-1"


def day_folder_name(d: date) -> str:
    return d.isoformat()


def build_output_path(
    root: Path, order_id_raw: str, packer_raw: str, when: datetime, *, suffix: str = ""
) -> Path:
    oid = sanitize_order_id(order_id_raw)
    pk = sanitize_packer_label(packer_raw)
    day = day_folder_name(when.date())
    # Giống thư mục ngày (YYYY-MM-DD); giờ dùng gạch (Windows cấm ':' trong tên file).
    stamp = f"{when:%Y-%m-%d}_{when:%H-%M-%S}"
    tail = ""
    if suffix.strip():
        tail = f"_{sanitize_packer_label(suffix)}"
    return root / day / f"{oid}_{pk}_{stamp}{tail}.mp4"
