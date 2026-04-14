from packrecorder.hid_report_parse import parse_hid_barcode_report


def test_ascii_suffix_null_profile() -> None:
    raw = bytes([0x01]) + b"ABC123\x00"
    assert parse_hid_barcode_report(raw, profile="ascii_suffix_null") == "ABC123"


def test_unknown_profile_raises() -> None:
    try:
        parse_hid_barcode_report(b"abc", profile="no_such")
    except ValueError as e:
        assert "Unknown HID barcode profile" in str(e)
    else:
        raise AssertionError("expected ValueError")
