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

CODE128_FILES: dict[str, str] = {
    "code128-usb-com": "881001133.",
    "code128-usb-hid": "881001131.",
    "code128-usb-keyboard": "881001124.",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for stem, data in CODES.items():
        img = qrcode.make(data, box_size=6, border=2)
        img.save(OUT / f"{stem}.png")
        print(f"Wrote {OUT / f'{stem}.png'} ({data!r})")

    try:
        from barcode import Code128
        from barcode.writer import ImageWriter
    except ImportError:
        print(
            "Skip Code128: pip install 'python-barcode[images]' pillow",
        )
        return

    writer = ImageWriter()
    writer.set_options({"module_height": 12.0, "quiet_zone": 2.0})
    for stem, data in CODE128_FILES.items():
        path_base = OUT / stem
        Code128(data, writer=writer).save(str(path_base))
        print(f"Wrote {path_base}.png ({data!r})")


if __name__ == "__main__":
    main()
