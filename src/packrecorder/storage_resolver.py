from __future__ import annotations

from pathlib import Path


def _is_writable_dir(p: Path) -> bool:
    if not p.exists():
        return False
    if not p.is_dir():
        return False
    try:
        probe = p / ".packrecorder_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def choose_write_root(primary: Path, backup: Path | None) -> tuple[Path, str]:
    """
    Trả về (root, "primary"|"backup"). Ưu tiên primary nếu thư mục tồn tại và ghi thử được.
    """
    if _is_writable_dir(primary):
        return primary, "primary"
    if backup is not None and _is_writable_dir(backup):
        return backup, "backup"
    primary.mkdir(parents=True, exist_ok=True)
    if _is_writable_dir(primary):
        return primary, "primary"
    if backup is not None:
        backup.mkdir(parents=True, exist_ok=True)
        if _is_writable_dir(backup):
            return backup, "backup"
    raise OSError("Không ghi được vào primary hay backup.")
