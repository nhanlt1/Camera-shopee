"""Helpers for lightweight RTSP probe in setup wizard."""

from __future__ import annotations


def validate_rtsp_probe_result(open_ok: bool, width: int, height: int) -> tuple[bool, str]:
    if not open_ok:
        return (False, "Không mở được luồng RTSP.")
    if width <= 0 or height <= 0:
        return (False, "Đã mở RTSP nhưng chưa nhận được khung hình hợp lệ.")
    return (True, f"Kết nối RTSP OK ({width}x{height}).")
