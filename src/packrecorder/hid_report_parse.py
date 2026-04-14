"""Parse HID keyboard/POS barcode reports into plain text (no device required)."""

from __future__ import annotations


def parse_hid_barcode_report(data: bytes, profile: str) -> str:
    """
    Decode raw HID report bytes to a barcode/order string.

    Profiles:
    - ascii_suffix_null: first byte is report ID; payload is ASCII until 0x00.
    """
    if not data:
        return ""
    if profile == "ascii_suffix_null":
        payload = data[1:] if len(data) > 1 else data
        n = payload.find(b"\x00")
        if n >= 0:
            payload = payload[:n]
        return payload.decode("ascii", errors="replace").strip()
    raise ValueError(f"Unknown HID barcode profile: {profile!r}")
