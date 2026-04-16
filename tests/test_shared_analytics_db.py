from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from packrecorder.config import AppConfig
from packrecorder.recording_index import RecordingIndex
from packrecorder.shared_analytics_db import (
    append_shared_analytics_record,
    make_record_uid,
    shared_analytics_db_path,
)


def test_make_record_uid_stable() -> None:
    a = make_record_uid(
        machine_id="m1",
        station_name="Máy 1",
        order_id="ORD-1",
        created_at="2026-04-16T10:00:00",
        rel_key="2026-04-16/ORD-1.mp4",
    )
    b = make_record_uid(
        machine_id="m1",
        station_name="Máy 1",
        order_id="ORD-1",
        created_at="2026-04-16T10:00:00",
        rel_key="2026-04-16/ORD-1.mp4",
    )
    assert a == b


def test_append_shared_analytics_record_ignore_duplicate(tmp_path: Path) -> None:
    cfg = AppConfig(video_root=str(tmp_path), software_id="sw-a", machine_id="m1")
    p = shared_analytics_db_path(cfg)
    assert p is not None
    ok1 = append_shared_analytics_record(
        cfg,
        order_id="ORD-1",
        packer="Máy 1",
        station_name="Máy 1",
        rel_key="2026-04-16/ORD-1.mp4",
        storage_status="pending_upload",
        primary_root=str(tmp_path),
        backup_root=None,
        resolved_path=str(tmp_path / "ORD-1.mp4"),
        created_at="2026-04-16T10:00:00",
        duration_seconds=30.0,
    )
    assert ok1 is True
    ok2 = append_shared_analytics_record(
        cfg,
        order_id="ORD-1",
        packer="Máy 1",
        station_name="Máy 1",
        rel_key="2026-04-16/ORD-1.mp4",
        storage_status="pending_upload",
        primary_root=str(tmp_path),
        backup_root=None,
        resolved_path=str(tmp_path / "ORD-1.mp4"),
        created_at="2026-04-16T10:00:00",
        duration_seconds=30.0,
    )
    assert ok2 is False
    idx = RecordingIndex(p)
    idx.connect(uri_readonly=True)
    try:
        rows = idx.search_dashboard(
            date_from="2026-04-16T00:00:00",
            date_to="2026-04-16T23:59:59",
            software_id="sw-a",
            limit=100,
        )
        assert len(rows) == 1
    finally:
        idx.close()


def test_shared_analytics_multi_machine_aggregate(tmp_path: Path) -> None:
    base = AppConfig(video_root=str(tmp_path), software_id="sw-b", machine_id="m1")
    cfg1 = replace(base, machine_id="m1")
    cfg2 = replace(base, machine_id="m2")
    assert append_shared_analytics_record(
        cfg1,
        order_id="ORD-1",
        packer="Máy 1",
        station_name="Máy 1",
        rel_key="a.mp4",
        storage_status="synced",
        primary_root=str(tmp_path),
        backup_root=None,
        resolved_path=str(tmp_path / "a.mp4"),
        created_at="2026-04-16T10:00:00",
        duration_seconds=10.0,
    )
    assert append_shared_analytics_record(
        cfg2,
        order_id="ORD-2",
        packer="Máy 2",
        station_name="Máy 2",
        rel_key="b.mp4",
        storage_status="pending_upload",
        primary_root=str(tmp_path),
        backup_root=None,
        resolved_path=str(tmp_path / "b.mp4"),
        created_at="2026-04-16T11:00:00",
        duration_seconds=15.0,
    )
    p = shared_analytics_db_path(base)
    assert p is not None
    idx = RecordingIndex(p)
    idx.connect(uri_readonly=True)
    try:
        rows = idx.search_dashboard(
            date_from="2026-04-16T00:00:00",
            date_to="2026-04-16T23:59:59",
            software_id="sw-b",
            limit=100,
        )
        assert len(rows) == 2
    finally:
        idx.close()
