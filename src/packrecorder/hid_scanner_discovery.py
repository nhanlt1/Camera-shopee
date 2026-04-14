"""Enumerate HID devices, filter likely barcode scanners, diff unplug/plug snapshots."""

from __future__ import annotations

from typing import Any, List, Tuple

HID_POS_USAGE_PAGE = 0x8C

_NAME_HINTS = (
    "scanner",
    "barcode",
    "honeywell",
    "zebra",
    "symbol",
    "datalogic",
    "cipherlab",
)


def _normalize_path_key(path: Any) -> bytes:
    if path is None:
        return b""
    if isinstance(path, bytes):
        return path
    if isinstance(path, (bytearray, memoryview)):
        return bytes(path)
    return str(path).encode("utf-8", errors="surrogatepass")


def device_fingerprint(d: dict[str, Any]) -> tuple[Any, ...]:
    path = d.get("path")
    if path is not None:
        return ("path", _normalize_path_key(path))
    return (
        "ids",
        int(d.get("vendor_id") or 0),
        int(d.get("product_id") or 0),
        (d.get("serial_number") or "") or "",
        int(d.get("interface_number") if d.get("interface_number") is not None else -1),
    )


def _name_lower(d: dict[str, Any]) -> str:
    ps = d.get("product_string") or ""
    ms = d.get("manufacturer_string") or ""
    return f"{ps} {ms}".lower()


def filter_scanner_candidates(devices: List[dict[str, Any]]) -> List[dict[str, Any]]:
    out: List[dict[str, Any]] = []
    for d in devices:
        up = int(d.get("usage_page") or 0)
        name = _name_lower(d)
        if up == HID_POS_USAGE_PAGE:
            out.append(d)
            continue
        if any(h in name for h in _NAME_HINTS):
            out.append(d)
    return out


def list_usage_page_devices(devices: List[dict[str, Any]], page: int) -> List[dict[str, Any]]:
    p = int(page)
    return [d for d in devices if int(d.get("usage_page") or 0) == p]


def diff_snapshots(
    before: List[dict[str, Any]], after: List[dict[str, Any]]
) -> Tuple[List[dict[str, Any]], List[dict[str, Any]]]:
    b = {device_fingerprint(x): x for x in before}
    a = {device_fingerprint(x): x for x in after}
    removed_keys = sorted(b.keys() - a.keys())
    added_keys = sorted(a.keys() - b.keys())
    removed = [b[k] for k in removed_keys]
    added = [a[k] for k in added_keys]
    return removed, added


def enumerate_hid_or_error() -> tuple[list[dict[str, Any]] | None, str | None]:
    try:
        import hid  # type: ignore  # gói PyPI: hidapi (module vẫn tên hid)
    except ImportError:
        return None, (
            "Gói Python 'hidapi' chưa có (cung cấp module import hid). "
            "Chạy: pip install 'hidapi>=0.14' hoặc pip install -e ."
        )
    try:
        raw = hid.enumerate()
    except Exception as e:
        return None, f"hid.enumerate() failed: {e}"
    return list(raw), None


def vid_pid_int_from_device(d: dict[str, Any]) -> tuple[int, int]:
    return int(d.get("vendor_id") or 0), int(d.get("product_id") or 0)


def device_label(d: dict[str, Any]) -> str:
    vid, pid = vid_pid_int_from_device(d)
    name = (d.get("product_string") or "").strip() or "(no name)"
    return f"{name} — VID {vid:04X} PID {pid:04X}"
