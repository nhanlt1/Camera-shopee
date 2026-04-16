from packrecorder.config import StationConfig
from packrecorder.ui.setup_wizard_scanner import (
    apply_scanner_choice_camera_decode,
    apply_scanner_choice_com,
    apply_scanner_choice_hid,
)


def _st() -> StationConfig:
    return StationConfig(
        "sid-a",
        "Máy 1",
        0,
        0,
    )


def test_com_sets_port_and_kind() -> None:
    s = apply_scanner_choice_com(_st(), port="COM3")
    assert s.scanner_input_kind == "com"
    assert s.scanner_serial_port == "COM3"


def test_hid_sets_vid_pid() -> None:
    s = apply_scanner_choice_hid(_st(), vid="1a2b", pid="3c4d")
    assert s.scanner_input_kind == "hid_pos"
    assert s.scanner_usb_vid == "1A2B"


def test_camera_decode_aligns_decode_index() -> None:
    s = apply_scanner_choice_camera_decode(_st())
    assert s.decode_camera_index == s.record_camera_index
