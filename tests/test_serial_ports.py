"""Kiểm tra heuristic lọc cổng COM."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from packrecorder.serial_ports import (
    _port_likely_usb_uart,
    format_serial_port_label,
    list_filtered_serial_ports,
)


def test_port_likely_usb_uart_with_vid() -> None:
    p = MagicMock()
    p.description = "Generic"
    p.vid = 0x1A86
    p.hwid = ""
    assert _port_likely_usb_uart(p) is True


def test_port_likely_rejects_bluetooth() -> None:
    p = MagicMock()
    p.description = "Standard Serial over Bluetooth link"
    p.vid = None
    p.hwid = ""
    assert _port_likely_usb_uart(p) is False


def test_port_likely_usb_name_token() -> None:
    p = MagicMock()
    p.description = "USB-SERIAL CH340 (COM5)"
    p.vid = None
    p.hwid = ""
    assert _port_likely_usb_uart(p) is True


def test_list_filtered_falls_back_when_usbish_empty() -> None:
    p = MagicMock()
    p.device = "COM1"
    p.description = "Communications Port"
    p.manufacturer = ""
    p.product = ""
    p.serial_number = None
    p.vid = None
    p.pid = None
    p.hwid = ""

    with patch("packrecorder.serial_ports.iter_raw_comports", return_value=[p]):
        with patch("packrecorder.serial_ports._try_open_port", return_value=True):
            out = list_filtered_serial_ports()
    assert out == [("COM1", "COM1 — Communications Port")]


def test_list_filtered_skips_try_open_when_disabled() -> None:
    p = MagicMock()
    p.device = "COM9"
    p.description = "USB-SERIAL"
    p.vid = 0x1A86
    p.pid = 0x7523
    p.manufacturer = ""
    p.product = ""
    p.serial_number = None
    p.hwid = ""

    mock_try = MagicMock()

    with patch("packrecorder.serial_ports.iter_raw_comports", return_value=[p]):
        with patch("packrecorder.serial_ports._try_open_port", mock_try):
            out = list_filtered_serial_ports(try_open_ports=False)
    mock_try.assert_not_called()
    assert out[0][0] == "COM9"
    assert "USB-SERIAL" in out[0][1]
    assert "VID:1A86" in out[0][1] and "PID:7523" in out[0][1]


def test_format_serial_port_label_includes_manufacturer() -> None:
    p = MagicMock()
    p.device = "COM4"
    p.description = "USB Serial Device"
    p.manufacturer = "Honeywell"
    p.product = ""
    p.vid = 0x0C2E
    p.pid = 0x0B61
    p.serial_number = "ABC12"
    p.hwid = ""
    s = format_serial_port_label(p)
    assert "COM4" in s and "Honeywell" in s
    assert "VID:0C2E" in s and "PID:0B61" in s
    assert "SN:ABC12" in s
