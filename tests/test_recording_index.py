from pathlib import Path

import pytest

from packrecorder.config import AppConfig
from packrecorder import recording_index as recording_index_mod
from packrecorder.recording_index import RecordingIndex, recordings_db_path_for_search


def test_recordings_db_path_for_search_prefers_primary(tmp_path: Path) -> None:
    cfg = AppConfig(video_root=str(tmp_path))
    p = tmp_path / "PackRecorder" / "recordings.sqlite"
    p.parent.mkdir(parents=True)
    p.write_bytes(b"")
    assert recordings_db_path_for_search(cfg) == p


def test_recordings_db_path_for_search_fallback_when_primary_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fb = tmp_path / "fallback.sqlite"
    fb.write_bytes(b"")
    monkeypatch.setattr(recording_index_mod, "fallback_index_path", lambda: fb)
    cfg = AppConfig(video_root=str(tmp_path))
    assert recordings_db_path_for_search(cfg) == fb


def test_recordings_db_path_for_search_uses_fallback_without_video_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """open_recording_index ghi vào fallback khi không có video_root — tìm kiếm phải đọc cùng file."""
    fb = tmp_path / "fallback.sqlite"
    fb.write_bytes(b"")
    monkeypatch.setattr(recording_index_mod, "fallback_index_path", lambda: fb)
    cfg = AppConfig(video_root="")
    assert recordings_db_path_for_search(cfg) == fb


def test_insert_and_search(tmp_path: Path) -> None:
    db = tmp_path / "i.sqlite"
    idx = RecordingIndex(db)
    idx.connect()
    idx.insert(
        order_id="ORD1",
        packer="M1",
        rel_key="2026-04-08/ORD1_M1_2026-04-08_12-00-00.mp4",
        storage_status="local_only",
        primary_root=str(tmp_path / "p"),
        backup_root=str(tmp_path / "b"),
        resolved_path=str(tmp_path / "b" / "f.mp4"),
        created_at="2026-04-08T12:00:00",
    )
    rows = idx.search(order_substring="ORD")
    idx.close()
    assert len(rows) == 1
    assert rows[0]["order_id"] == "ORD1"


def test_search_storage_status_in(tmp_path: Path) -> None:
    db = tmp_path / "in.sqlite"
    idx = RecordingIndex(db)
    idx.connect()
    for oid, st in (
        ("A", "synced"),
        ("B", "pending_upload"),
        ("C", "local_only"),
    ):
        idx.insert(
            order_id=oid,
            packer="M",
            rel_key=f"2026-04-08/{oid}.mp4",
            storage_status=st,
            primary_root=str(tmp_path),
            backup_root=str(tmp_path),
            resolved_path=str(tmp_path / f"{oid}.mp4"),
            created_at="2026-04-08T12:00:00",
        )
    rows = idx.search(
        storage_status_in=["local_only", "pending_upload"],
    )
    idx.close()
    got = {r["order_id"] for r in rows}
    assert got == {"B", "C"}


def test_insert_stores_duration_and_delete_by_id(tmp_path: Path) -> None:
    db = tmp_path / "duration.sqlite"
    idx = RecordingIndex(db)
    idx.connect()
    idx.insert(
        order_id="D1",
        packer="M1",
        rel_key="2026-04-08/D1.mp4",
        storage_status="local_only",
        primary_root=str(tmp_path),
        backup_root=None,
        resolved_path=str(tmp_path / "D1.mp4"),
        created_at="2026-04-08T12:00:00",
        duration_seconds=12.4,
    )
    rows = idx.search(order_substring="D1")
    assert len(rows) == 1
    assert float(rows[0]["duration_seconds"]) == pytest.approx(12.4, rel=0.01)
    idx.delete_by_id(int(rows[0]["id"]))
    rows_after = idx.search(order_substring="D1")
    idx.close()
    assert rows_after == []
