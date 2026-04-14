from __future__ import annotations

from packrecorder.hid_scanner_discovery import (
    HID_POS_USAGE_PAGE,
    device_fingerprint,
    diff_snapshots,
    filter_scanner_candidates,
    list_usage_page_devices,
)


def test_device_fingerprint_stable_order() -> None:
    d = {
        "vendor_id": 0x05E0,
        "product_id": 0x1200,
        "serial_number": "ABC",
        "path": b"\\\\?\\hid#vid_05e0&pid_1200",
        "interface_number": 0,
    }
    assert device_fingerprint(d) == device_fingerprint(dict(d))


def test_filter_scanner_candidates_by_name_and_usage() -> None:
    devices = [
        {"vendor_id": 1, "product_id": 2, "product_string": "Honeywell Scanner", "usage_page": 0xFFFF},
        {"vendor_id": 3, "product_id": 4, "product_string": "Generic Keyboard", "usage_page": 0x01},
        {"vendor_id": 5, "product_id": 6, "product_string": "Unknown", "usage_page": HID_POS_USAGE_PAGE},
    ]
    out = filter_scanner_candidates(devices)
    vids = {x["vendor_id"] for x in out}
    assert 1 in vids and 5 in vids
    assert 3 not in vids


def test_diff_snapshots_removed_and_added() -> None:
    before = [
        {"vendor_id": 1, "product_id": 1, "serial_number": None, "path": b"p1", "interface_number": -1},
        {"vendor_id": 2, "product_id": 2, "serial_number": None, "path": b"p2", "interface_number": -1},
    ]
    after = [
        {"vendor_id": 2, "product_id": 2, "serial_number": None, "path": b"p2", "interface_number": -1},
        {"vendor_id": 3, "product_id": 3, "serial_number": None, "path": b"p3", "interface_number": -1},
    ]
    removed, added = diff_snapshots(before, after)
    assert len(removed) == 1 and removed[0]["vendor_id"] == 1
    assert len(added) == 1 and added[0]["vendor_id"] == 3


def test_list_usage_page_devices() -> None:
    devices = [
        {"vendor_id": 1, "product_id": 1, "usage_page": 0x8C},
        {"vendor_id": 2, "product_id": 2, "usage_page": 0x01},
    ]
    only = list_usage_page_devices(devices, HID_POS_USAGE_PAGE)
    assert len(only) == 1 and only[0]["vendor_id"] == 1
