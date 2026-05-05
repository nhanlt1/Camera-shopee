from packrecorder.config import AppConfig, StationConfig
from packrecorder.ui.setup_wizard import (
    filter_camera_indices_for_wizard,
    filter_com_ports_for_wizard,
    scanner_default_mode_id,
)


def _cfg() -> AppConfig:
    cfg = AppConfig()
    cfg.stations = [
        StationConfig("s1", "Máy 1", 0, 0),
        StationConfig("s2", "Máy 2", 1, 1),
    ]
    return cfg


def test_scanner_default_mode_fresh_state_is_visible() -> None:
    """Fresh state (kind=com, no port) → mode «visible» (0)."""
    st = StationConfig("s", "Máy", 0, 0)
    assert scanner_default_mode_id(st) == 0


def test_scanner_default_mode_keeps_hid_as_background() -> None:
    """HID POS đã có VID/PID → mode «background» (1)."""
    st = StationConfig("s", "Máy", 0, 0)
    st.scanner_input_kind = "hid_pos"
    st.scanner_usb_vid = "1A2B"
    st.scanner_usb_pid = "3C4D"
    assert scanner_default_mode_id(st) == 1


def test_scanner_default_mode_com_with_port_is_background() -> None:
    """COM đã có cổng → mode «background» (1)."""
    st = StationConfig("s", "Máy", 0, 0)
    st.scanner_input_kind = "com"
    st.scanner_serial_port = "COM5"
    assert scanner_default_mode_id(st) == 1


def test_scanner_default_mode_keyboard_wedge_is_visible() -> None:
    """Wedge keyboard → mode «visible» (0)."""
    st = StationConfig("s", "Máy", 0, 0)
    st.scanner_input_kind = "keyboard"
    assert scanner_default_mode_id(st) == 0


def test_scanner_default_mode_camera_is_visible() -> None:
    """Camera decode → mode «visible» (0)."""
    st = StationConfig("s", "Máy", 0, 0)
    st.scanner_input_kind = "camera"
    assert scanner_default_mode_id(st) == 0


def test_filter_camera_indices_for_machine2_excludes_machine1_usb() -> None:
    cfg = _cfg()
    cfg.stations[0].record_camera_kind = "usb"
    cfg.stations[0].record_camera_index = 1
    out = filter_camera_indices_for_wizard([0, 1, 2], cfg, 1)
    assert out == [0, 2]


def test_filter_com_ports_for_machine2_excludes_machine1_port() -> None:
    cfg = _cfg()
    cfg.stations[0].scanner_serial_port = "COM7"
    raw = [("COM7", "USB Serial COM7"), ("COM8", "USB Serial COM8")]
    out = filter_com_ports_for_wizard(raw, cfg, 1)
    assert out == [("COM8", "USB Serial COM8")]
