from packrecorder.config import StationConfig
from packrecorder.ui.setup_wizard_scanner import (
    apply_scanner_choice_camera_decode,
    apply_scanner_choice_com,
    apply_scanner_choice_hid,
    apply_scanner_choice_keyboard_wedge,
    auto_apply_background_scanner,
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
    assert s.scanner_input_kind == "camera"
    assert s.decode_camera_index == s.record_camera_index


def test_keyboard_wedge_clears_serial_and_vidpid() -> None:
    base = _st()
    base.scanner_serial_port = "COM5"
    base.scanner_usb_vid = "0C2E"
    base.scanner_usb_pid = "0B61"
    s = apply_scanner_choice_keyboard_wedge(base)
    assert s.scanner_input_kind == "keyboard"
    assert s.scanner_serial_port == ""
    assert s.scanner_usb_vid == ""
    assert s.scanner_usb_pid == ""


def test_auto_apply_background_picks_first_com_port() -> None:
    s = auto_apply_background_scanner(
        _st(),
        ports=[("COM7", "USB Serial COM7"), ("COM8", "USB Serial COM8")],
    )
    assert s is not None
    assert s.scanner_input_kind == "com"
    assert s.scanner_serial_port == "COM7"


def test_auto_apply_background_keeps_previous_port_if_still_present() -> None:
    base = _st()
    base.scanner_serial_port = "COM8"
    s = auto_apply_background_scanner(
        base,
        ports=[("COM7", "USB Serial COM7"), ("COM8", "USB Serial COM8")],
    )
    assert s is not None
    assert s.scanner_serial_port == "COM8"


def test_auto_apply_background_falls_back_to_existing_hid() -> None:
    base = _st()
    base.scanner_input_kind = "hid_pos"
    base.scanner_usb_vid = "0C2E"
    base.scanner_usb_pid = "0B61"
    s = auto_apply_background_scanner(base, ports=[])
    assert s is not None
    assert s.scanner_input_kind == "hid_pos"
    assert s.scanner_usb_vid == "0C2E"


def test_auto_apply_background_returns_none_when_no_devices() -> None:
    s = auto_apply_background_scanner(_st(), ports=[])
    assert s is None
