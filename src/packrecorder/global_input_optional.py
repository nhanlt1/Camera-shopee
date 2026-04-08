"""Optional global keyboard capture (not implemented — high risk with Qt / wedge scanners)."""

from __future__ import annotations

from typing import Any


def try_enable_global_barcode_hook(parent_widget: Any) -> None:
    """Deprecated: global HID hook is intentionally disabled in COM-only workflow."""
    from PySide6.QtWidgets import QMessageBox

    QMessageBox.warning(
        parent_widget,
        "Chưa hỗ trợ",
        "Lắng nghe mã toàn cục (pynput) không được bật trong bản này.\n\n"
        "Ứng dụng dùng luồng COM (serial) để nhận mã chạy nền ổn định, không phụ thuộc focus.\n"
        "Máy quét kiểu bàn phím (HID) sẽ gửi ký tự vào app đang focus (Excel, Chrome, Zalo…).",
    )
