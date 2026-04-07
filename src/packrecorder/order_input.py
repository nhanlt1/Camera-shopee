"""Chuẩn hoá mã đơn từ ô nhập / máy quét."""

from __future__ import annotations


def normalize_manual_order_text(raw: str) -> str:
    """Strip và chỉ lấy dòng đầu (bỏ xuống dòng thừa)."""
    s = (raw or "").strip()
    if not s:
        return ""
    for sep in ("\r\n", "\n", "\r"):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
            break
    return s
