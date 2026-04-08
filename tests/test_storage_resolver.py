from pathlib import Path

from packrecorder.storage_resolver import choose_write_root


def test_backup_none_uses_primary(tmp_path: Path) -> None:
    p = tmp_path / "p"
    p.mkdir()
    root, tag = choose_write_root(p, None)
    assert root == p
    assert tag == "primary"


def test_primary_missing_uses_backup(tmp_path: Path) -> None:
    backup = tmp_path / "b"
    backup.mkdir()
    primary = tmp_path / "missing" / "p"
    root, tag = choose_write_root(primary, backup)
    assert root == backup
    assert tag == "backup"
