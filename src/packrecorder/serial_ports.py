"""Lọc cổng COM cho máy quét USB–serial (giảm cổng ảo / Bluetooth trên Windows)."""

from __future__ import annotations

import re
from typing import Any

_BLUETOOTH_HINTS = (
    "bluetooth",
    "standard serial over bluetooth",
    "btlink",
)
_SKIP_DESC = (
    "intel(r) active management",
    "intel active management",
)
_USB_NAME_TOKENS = (
    "usb",
    "ch340",
    "cp210",
    "ftdi",
    "pl2303",
    "cp21",
    "silicon labs",
    "wch.cn",
    "prolific",
)
_SCANNER_HINT_TOKENS = (
    "scanner",
    "barcode",
    "usb serial",
    "symbol",
    "zebra",
    "honeywell",
    "datalogic",
)


def _port_likely_usb_uart(p: Any) -> bool:
    desc = (getattr(p, "description", None) or "").lower()
    if any(h in desc for h in _BLUETOOTH_HINTS):
        return False
    if any(s in desc for s in _SKIP_DESC):
        return False
    if getattr(p, "vid", None) is not None:
        return True
    hw = (getattr(p, "hwid", None) or "").upper()
    if "VID_" in hw and "PID_" in hw:
        return True
    return any(t in desc for t in _USB_NAME_TOKENS)


def format_serial_port_label(p: Any) -> str:
    """Nhãn một dòng: COMx — mô tả Windows + hãng + VID:PID (+ SN ngắn) để phân biệt thiết bị."""
    dev = (getattr(p, "device", None) or "").strip() or "?"
    chunks: list[str] = []
    desc = str(getattr(p, "description", None) or "").strip()
    if desc:
        chunks.append(desc)
    mfr = str(getattr(p, "manufacturer", None) or "").strip()
    if mfr and mfr.lower() not in desc.lower():
        chunks.append(mfr)
    prod = str(getattr(p, "product", None) or "").strip()
    if prod and prod.lower() not in desc.lower() and prod.lower() != mfr.lower():
        chunks.append(prod)
    vid = getattr(p, "vid", None)
    pid = getattr(p, "pid", None)
    if isinstance(vid, int) and isinstance(pid, int):
        chunks.append(f"VID:{vid:04X} PID:{pid:04X}")
    else:
        hw = (getattr(p, "hwid", None) or "").strip()
        if hw and "VID_" in hw.upper():
            m = re.search(r"VID_([0-9A-F]{4}).*PID_([0-9A-F]{4})", hw, re.I)
            if m:
                chunks.append(f"VID:{m.group(1)} PID:{m.group(2)}")
    sn = getattr(p, "serial_number", None)
    s = str(sn).strip() if sn is not None else ""
    if 4 <= len(s) <= 28 and s not in ("None", ""):
        chunks.append(f"SN:{s}")
    body = " · ".join(chunks) if chunks else "Serial"
    return f"{dev} — {body}"


def port_vid_pid_hex(p: Any) -> tuple[str, str]:
    """Lấy VID/PID dạng HEX 4 ký tự từ pyserial ListPortInfo ('' nếu không có)."""
    vid = getattr(p, "vid", None)
    pid = getattr(p, "pid", None)
    if isinstance(vid, int) and isinstance(pid, int):
        return (f"{vid:04X}", f"{pid:04X}")
    hw = (getattr(p, "hwid", None) or "").strip()
    if hw and "VID_" in hw.upper():
        m = re.search(r"VID_([0-9A-F]{4}).*PID_([0-9A-F]{4})", hw, re.I)
        if m:
            return (m.group(1).upper(), m.group(2).upper())
    return ("", "")


def vid_pid_by_device() -> dict[str, tuple[str, str]]:
    out: dict[str, tuple[str, str]] = {}
    for p in iter_raw_comports():
        dev = (getattr(p, "device", None) or "").strip()
        if not dev:
            continue
        out[dev] = port_vid_pid_hex(p)
    return out


def _port_sort_key(p: Any, can_open: bool) -> tuple:
    """Ưu tiên: mở được (probe) → giống USB UART → không Bluetooth → không Intel AMT → tên cổng."""
    desc = (getattr(p, "description", None) or "").lower()
    bt = 1 if any(h in desc for h in _BLUETOOTH_HINTS) else 0
    skip = 1 if any(s in desc for s in _SKIP_DESC) else 0
    usb = 1 if _port_likely_usb_uart(p) else 0
    co = 0 if can_open else 1
    device = getattr(p, "device", "") or ""
    return (co, -usb, bt, skip, device)


def _try_open_port(device: str) -> bool:
    try:
        import serial
    except ImportError:
        return True
    try:
        ser = serial.Serial(device, timeout=0.05)
        ser.close()
        return True
    except Exception as e:
        err = str(e).lower()
        if (
            "access is denied" in err
            or "being used" in err
            or "permission" in err
            or "busy" in err
        ):
            return True
        return False


def iter_raw_comports() -> list[Any]:
    try:
        from serial.tools import list_ports as serial_list_ports
    except Exception:
        return []
    try:
        return list(serial_list_ports.comports())
    except Exception:
        return []


def list_filtered_serial_ports(*, try_open_ports: bool = True) -> list[tuple[str, str]]:
    """(device, label) — liệt kê mọi cổng với nhãn đầy đủ; sắp xếp ưu tiên USB/mở được.

    try_open_ports=True: thử mở từng cổng (chậm hơn, dùng khi bấm Làm mới).
    try_open_ports=False: không mở cổng; vẫn lấy tên thiết bị từ hệ điều hành.
    """
    ports = iter_raw_comports()
    if not ports:
        return []

    can_open: dict[str, bool] = {}
    for p in ports:
        dev = getattr(p, "device", None) or ""
        if not dev:
            continue
        if try_open_ports:
            can_open[dev] = _try_open_port(dev)
        else:
            can_open[dev] = True

    ordered = sorted(
        ports,
        key=lambda p: _port_sort_key(p, can_open.get(getattr(p, "device", ""), True)),
    )

    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for p in ordered:
        dev = getattr(p, "device", None) or ""
        if not dev or dev in seen:
            continue
        seen.add(dev)
        out.append((dev, format_serial_port_label(p)))
    return out


def _scanner_hint_score(p: Any) -> int:
    text = " ".join(
        (
            str(getattr(p, "description", None) or ""),
            str(getattr(p, "manufacturer", None) or ""),
            str(getattr(p, "product", None) or ""),
        )
    ).lower()
    return sum(1 for tk in _SCANNER_HINT_TOKENS if tk in text)


def choose_serial_port(
    *,
    selected_port: str,
    expected_vid: str = "",
    expected_pid: str = "",
    try_open_ports: bool = True,
) -> tuple[str, bool]:
    """Chọn cổng COM tốt nhất.

    Ưu tiên:
    1) Cổng đã chọn (nếu còn tồn tại).
    2) Match VID/PID kỳ vọng.
    3) Heuristic theo tên scanner/USB.
    4) Fallback rỗng (camera decode).
    Returns: (device, auto_detected).
    """
    sp = (selected_port or "").strip()
    vid = (expected_vid or "").strip().upper().removeprefix("0X")
    pid = (expected_pid or "").strip().upper().removeprefix("0X")
    ports = iter_raw_comports()
    if not ports:
        return (sp, False) if sp else ("", False)
    by_device = {(getattr(p, "device", None) or "").strip(): p for p in ports}
    if sp and sp in by_device:
        return (sp, False)

    can_open: dict[str, bool] = {}
    for p in ports:
        dev = (getattr(p, "device", None) or "").strip()
        if not dev:
            continue
        can_open[dev] = _try_open_port(dev) if try_open_ports else True
    ordered = sorted(
        ports,
        key=lambda p: _port_sort_key(p, can_open.get(getattr(p, "device", ""), True)),
    )

    if len(vid) == 4 and len(pid) == 4:
        for p in ordered:
            pvid, ppid = port_vid_pid_hex(p)
            if pvid == vid and ppid == pid:
                dev = (getattr(p, "device", None) or "").strip()
                if dev:
                    return (dev, True)

    hinted = [p for p in ordered if _scanner_hint_score(p) > 0]
    if hinted:
        dev = (getattr(hinted[0], "device", None) or "").strip()
        if dev:
            return (dev, True)

    if sp:
        return (sp, False)
    return ("", False)
