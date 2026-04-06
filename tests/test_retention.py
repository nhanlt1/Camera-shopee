from datetime import date
from pathlib import Path

from packrecorder.retention import purge_old_day_folders


def test_purge_only_dated_folders_older_than_keep(tmp_path: Path):
    root = tmp_path
    old = root / "2026-03-01"
    old.mkdir()
    recent = root / "2026-04-01"
    recent.mkdir()
    junk = root / "not-a-date"
    junk.mkdir()
    today = date(2026, 4, 6)
    removed = purge_old_day_folders(root, keep_days=16, today=today)
    assert not old.exists()
    assert recent.exists()
    assert junk.exists()
    assert any("2026-03-01" in str(p) for p in removed) or not old.exists()
