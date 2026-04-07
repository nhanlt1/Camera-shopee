"""Log phiên run_errors.log."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture
def log_in_tmp_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.chdir(tmp_path)
    return tmp_path


def test_reset_then_append(log_in_tmp_cwd: Path) -> None:
    from packrecorder.session_log import (
        append_session_log,
        reset_session_log,
        session_log_path,
    )

    reset_session_log()
    p = session_log_path()
    assert p == log_in_tmp_cwd / "run_errors.log"
    assert p.parent.is_dir()
    first = p.read_text(encoding="utf-8")
    assert "=== Pack Recorder" in first
    assert "phiên làm việc" in first

    append_session_log("ERROR", "thử ghi lỗi")
    second = p.read_text(encoding="utf-8")
    assert "thử ghi lỗi" in second
    assert "[T+" in second and "[Δ+" in second
    assert second.startswith(first.split("\n")[0])  # header line preserved

    reset_session_log()
    third = p.read_text(encoding="utf-8")
    assert "thử ghi lỗi" not in third
    assert "=== Pack Recorder" in third


def test_append_startup_hints_writes_hint_lines(log_in_tmp_cwd: Path) -> None:
    from packrecorder.session_log import (
        STARTUP_HINT_LINES,
        append_startup_hints,
        reset_session_log,
        session_log_path,
    )

    reset_session_log()
    append_startup_hints()
    text = session_log_path().read_text(encoding="utf-8")
    assert text.count("HINT") >= len(STARTUP_HINT_LINES)
    assert "run_errors.log" in text
