"""Kiểm tra heuristic lọc cổng COM."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from packrecorder.serial_ports import _port_likely_usb_uart, list_filtered_serial_ports


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
    p.vid = None
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
    p.hwid = ""

    mock_try = MagicMock()

    with patch("packrecorder.serial_ports.iter_raw_comports", return_value=[p]):
        with patch("packrecorder.serial_ports._try_open_port", mock_try):
            out = list_filtered_serial_ports(try_open_ports=False)
    mock_try.assert_not_called()
    assert out == [("COM9", "COM9 — USB-SERIAL")]
