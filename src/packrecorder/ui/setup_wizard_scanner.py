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
        scanner_input_kind="camera",
        scanner_usb_vid="",
        scanner_usb_pid="",
        decode_camera_index=rec,
    )


def apply_scanner_choice_keyboard_wedge(st: StationConfig) -> StationConfig:
    """Wedge: scanner gõ phím trực tiếp vào ô «Mã đơn» (cần app focus)."""
    return replace(
        st,
        scanner_serial_port="",
        scanner_input_kind="keyboard",
        scanner_usb_vid="",
        scanner_usb_pid="",
    )


def auto_apply_background_scanner(
    st: StationConfig,
    *,
    ports: list[tuple[str, str]],
) -> StationConfig | None:
    """Tự gán scanner background:

    - Có cổng COM khả dụng → match VID/PID đã lưu (nếu có) hoặc dùng cổng đầu tiên.
    - Không có COM nhưng station đã có VID/PID HID POS → giữ HID POS.
    - Không có COM, không có HID POS đã lưu → trả về None để wizard mở dialog HID.
    """
    if ports:
        prev_port = (st.scanner_serial_port or "").strip()
        chosen = ""
        if prev_port:
            for dev, _label in ports:
                if (dev or "").strip() == prev_port:
                    chosen = prev_port
                    break
        if not chosen:
            chosen = (ports[0][0] or "").strip()
        if chosen:
            return apply_scanner_choice_com(st, port=chosen)
    if (st.scanner_usb_vid or "").strip() and (st.scanner_usb_pid or "").strip():
        return apply_scanner_choice_hid(
            st,
            vid=st.scanner_usb_vid,
            pid=st.scanner_usb_pid,
        )
    return None
