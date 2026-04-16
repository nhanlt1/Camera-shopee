from __future__ import annotations

from dataclasses import replace

from packrecorder.config import StationConfig


def apply_scanner_choice_com(st: StationConfig, *, port: str) -> StationConfig:
    port = (port or "").strip()
    return replace(
        st,
        scanner_serial_port=port,
        scanner_input_kind="com",
        scanner_usb_vid="",
        scanner_usb_pid="",
    )


def apply_scanner_choice_hid(st: StationConfig, *, vid: str, pid: str) -> StationConfig:
    return replace(
        st,
        scanner_serial_port="",
        scanner_input_kind="hid_pos",
        scanner_usb_vid=vid.strip().upper(),
        scanner_usb_pid=pid.strip().upper(),
    )


def apply_scanner_choice_camera_decode(st: StationConfig) -> StationConfig:
    rec = int(st.record_camera_index)
    return replace(
        st,
        scanner_serial_port="",
        scanner_input_kind="com",
        scanner_usb_vid="",
        scanner_usb_pid="",
        decode_camera_index=rec,
    )
