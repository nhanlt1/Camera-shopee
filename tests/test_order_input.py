"""Tests for normalize_manual_order_text."""

from __future__ import annotations

from packrecorder.order_input import normalize_manual_order_text


def test_strip() -> None:
    assert normalize_manual_order_text("  abc  ") == "abc"


def test_first_line_only() -> None:
    assert normalize_manual_order_text("line1\nline2") == "line1"
    assert normalize_manual_order_text("x\ry") == "x"


def test_repeated_halves_kept_verbatim() -> None:
    """Không gộp chuỗi dạng AB+AB — mã đơn có thể cố ý lặp pattern."""
    assert normalize_manual_order_text("ABAB") == "ABAB"
    assert normalize_manual_order_text("mnbmnb") == "mnbmnb"


def test_odd_length_no_dup_fold() -> None:
    assert normalize_manual_order_text("ABC") == "ABC"


def test_empty() -> None:
    assert normalize_manual_order_text("") == ""
    assert normalize_manual_order_text("   \n  ") == ""


def test_strip_hid_aim_qr_prefix() -> None:
    """Winson HID POS: tiền tố điều khiển + ]Q1 (AIM QR) trước payload thật."""
    assert (
        normalize_manual_order_text("\x14]Q1BESTMP0052261466VNA")
        == "BESTMP0052261466VNA"
    )
    assert normalize_manual_order_text("]Q1ORDER-123") == "ORDER-123"


def test_strip_datamatrix_aim_prefix() -> None:
    assert normalize_manual_order_text("]d2ABC123") == "ABC123"
