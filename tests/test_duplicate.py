from datetime import date
from pathlib import Path

from packrecorder.duplicate import is_duplicate_order
from packrecorder.paths import sanitize_order_id


def test_duplicate_when_prefix_exists(tmp_path: Path):
    root = tmp_path
    day = date(2026, 4, 6)
    day_dir = root / day.isoformat()
    day_dir.mkdir(parents=True)
    oid = sanitize_order_id("DON1")
    (day_dir / f"{oid}_Máy-1_20260406-120000.mp4").write_bytes(b"")
    assert is_duplicate_order(root, "DON1", day) is True


def test_not_duplicate_empty_day(tmp_path: Path):
    root = tmp_path
    day = date(2026, 4, 6)
    (root / day.isoformat()).mkdir(parents=True)
    assert is_duplicate_order(root, "NEW", day) is False
