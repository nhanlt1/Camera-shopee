"""Tạo lại QR PNG cho mã cấu hình chế độ Winson (USB COM / HID / Keyboard)."""
from __future__ import annotations

from pathlib import Path

import qrcode

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "scanner-config-codes" / "winson-mode-barcodes"

CODES: dict[str, str] = {
    "qr-usb-com": "881001133.",
    "qr-usb-hid": "881001131.",
    "qr-usb-keyboard": "881001124.",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for stem, data in CODES.items():
        img = qrcode.make(data, box_size=6, border=2)
        img.save(OUT / f"{stem}.png")
        print(f"Wrote {OUT / f'{stem}.png'} ({data!r})")


if __name__ == "__main__":
    main()
