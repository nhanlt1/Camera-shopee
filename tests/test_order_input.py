"""Tests for normalize_manual_order_text."""

from __future__ import annotations

from packrecorder.order_input import normalize_manual_order_text


def test_strip() -> None:
    assert normalize_manual_order_text("  abc  ") == "abc"


def test_first_line_only() -> None:
    assert normalize_manual_order_text("line1\nline2") == "line1"
    assert normalize_manual_order_text("x\ry") == "x"


def test_duplicate_halves() -> None:
    assert normalize_manual_order_text("ABAB") == "AB"
    assert normalize_manual_order_text("ABCABC") == "ABC"


def test_odd_length_no_dup_fold() -> None:
    assert normalize_manual_order_text("ABC") == "ABC"


def test_empty() -> None:
    assert normalize_manual_order_text("") == ""
    assert normalize_manual_order_text("   \n  ") == ""
