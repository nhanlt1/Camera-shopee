from datetime import datetime
from pathlib import Path

from packrecorder.paths import (
    build_output_path,
    sanitize_order_id,
    sanitize_packer_label,
)


def test_sanitize_replaces_invalid_chars_and_underscore():
    assert sanitize_order_id("a/b<c>") == "a-b-c"
    assert sanitize_order_id("ORD_001") == "ORD-001"


def test_sanitize_packer_spaces_underscore():
    assert sanitize_packer_label("Máy 1") == "Máy-1"
    assert sanitize_packer_label("Máy 2") == "Máy-2"
    assert sanitize_packer_label("A_B C") == "A-B-C"


def test_sanitize_packer_preserves_utf8_letters():
    assert sanitize_packer_label("Nguyễn Văn A") == "Nguyễn-Văn-A"
    assert "đ" in sanitize_packer_label("Quầy-đông")


def test_build_output_path_includes_packer():
    root = Path("D:/root")
    dt = datetime(2026, 4, 6, 14, 30, 0)
    p = build_output_path(root, "ORD001", "Máy 1", dt)
    assert p == Path("D:/root/2026-04-06/ORD001_Máy-1_2026-04-06_14-30-00.mp4")
    p2 = build_output_path(root, "ORD001", "Nguyễn A", dt)
    assert "Nguyễn-A" in p2.name
