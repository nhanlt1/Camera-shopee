"""Chuẩn hoá mã đơn từ ô nhập / máy quét (tránh dính đôi wedge)."""

from __future__ import annotations


def normalize_manual_order_text(raw: str) -> str:
    """Strip, một dòng; nếu chuỗi là hai nửa giống nhau (AB+AB) thì chỉ lấy một nửa."""
    s = (raw or "").strip()
    if not s:
        return ""
    for sep in ("\r\n", "\n", "\r"):
        if sep in s:
            s = s.split(sep, 1)[0].strip()
            break
    n = len(s)
    if n >= 2 and n % 2 == 0:
        half = n // 2
        if s[:half] == s[half:]:
            return s[:half]
    return s
