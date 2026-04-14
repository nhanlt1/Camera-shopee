"""
Smoke: thư viện HID thật (gói PyPI **hidapi**, `import hid`) phải load DLL và `enumerate()` được.

Khác `test_scan_flow_simulation.py`: không giả lập bytes — gọi hidapi thật (gần app khi chạy đúng venv).

- Chạy: ``.venv\\Scripts\\python -m pytest tests/test_hid_environment_smoke.py``
  (Python hệ thống thường thiếu wheel → ImportError → test bị **skip**, không phải pass giả.)

- Test này **không** mở VID/PID, **không** đọc report quét, **không** chạy FFmpeg / MainWindow.
"""

from __future__ import annotations

import pytest


def test_hidapi_import_and_enumerate() -> None:
    try:
        import hid
    except ImportError as e:
        pytest.skip(
            f"Không import được module hid ({e}). "
            "Dùng venv của project: .venv\\Scripts\\pip install -e . "
            "(cần gói hidapi, không phải gói hid ctypes thuần.)"
        )

    raw = hid.enumerate()
    assert isinstance(raw, list)
    for d in raw[: min(3, len(raw))]:
        assert "vendor_id" in d and "product_id" in d
