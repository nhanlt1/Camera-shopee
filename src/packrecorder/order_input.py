"""Chuẩn hoá mã đơn từ ô nhập / máy quét."""

from __future__ import annotations

import re

# Ký tự C0 / DEL do một số máy quét HID/COM gắn trước payload (ví dụ 0x14).
_LEADING_CONTROLS = re.compile(r"^[\x00-\x1F\x7F]+")
# ISO/IEC 15424 AIM symbology identifier: «]» + ký hiệu loại mã + bộ sửa (thường thấy ]Q1 cho QR trên Winson).
_AIM_SYM_PREFIX = re.compile(r"^\][A-Za-z][0-9A-Za-z]")


def normalize_manual_order_text(raw: str) -> str:
    """Strip và chỉ lấy dòng đầu (bỏ xuống dòng thừa)."""
    s = (raw or "").strip()
    if not s:
        return ""
    for sep in ("\r\n", "\n", "\r"):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
            break
    s = _LEADING_CONTROLS.sub("", s)
    s = _AIM_SYM_PREFIX.sub("", s)
    return s.strip()
