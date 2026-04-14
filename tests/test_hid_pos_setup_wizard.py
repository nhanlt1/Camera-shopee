from __future__ import annotations

from unittest.mock import patch

from PySide6.QtCore import Qt

from packrecorder.ui.hid_pos_setup_wizard import HidPosSetupWizard


def test_wizard_accept_emits_vid_pid(qapp: object) -> None:
    w = HidPosSetupWizard()
    w._pending_vid = 0x05E0
    w._pending_pid = 0x1200
    got: list[tuple[int, int]] = []
    w.vid_pid_chosen.connect(
        lambda a, b: got.append((a, b)),
        Qt.ConnectionType.DirectConnection,
    )
    w.accept()
    assert got == [(0x05E0, 0x1200)]


@patch("packrecorder.ui.hid_pos_setup_wizard.enumerate_hid_or_error")
def test_wizard_refresh_populates_list(mock_enum: object, qapp: object) -> None:
    mock_enum.return_value = (
        [
            {
                "vendor_id": 0x05E0,
                "product_id": 0x1200,
                "product_string": "TestScanner",
                "usage_page": 0x8C,
                "path": b"p1",
                "interface_number": -1,
            },
        ],
        None,
    )
    w = HidPosSetupWizard()
    w._refresh_device_list()
    assert w._list_devices.count() >= 1
    w._list_devices.setCurrentRow(0)
    w._on_list_selection_changed()
    assert w._pending_vid == 0x05E0 and w._pending_pid == 0x1200
