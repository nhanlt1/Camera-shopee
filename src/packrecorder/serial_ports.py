"""Lọc cổng COM cho máy quét USB–serial (giảm cổng ảo / Bluetooth trên Windows)."""

from __future__ import annotations

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
    except ImportError:
        return []
    return list(serial_list_ports.comports())


def list_filtered_serial_ports(*, try_open_ports: bool = True) -> list[tuple[str, str]]:
    """(device, label) — ưu tiên USB UART.

    try_open_ports=True: thử mở từng cổng (chậm, dùng khi bấm Làm mới).
    try_open_ports=False: chỉ heuristic + liệt kê (nhanh khi khởi động UI).
    """
    ports = iter_raw_comports()
    if not ports:
        return []

    usbish = [p for p in ports if _port_likely_usb_uart(p)]
    candidates = usbish if usbish else list(ports)
    if try_open_ports:
        opened_ok = [p for p in candidates if _try_open_port(p.device)]
        chosen = opened_ok if opened_ok else candidates
    else:
        chosen = candidates

    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for p in chosen:
        dev = p.device
        if dev in seen:
            continue
        seen.add(dev)
        desc = p.description or "Serial"
        out.append((dev, f"{dev} — {desc}"))

    if not out:
        for p in ports:
            if p.device in seen:
                continue
            seen.add(p.device)
            desc = p.description or "Serial"
            out.append((p.device, f"{p.device} — {desc}"))
    return out
