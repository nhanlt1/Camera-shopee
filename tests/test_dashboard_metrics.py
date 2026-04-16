from __future__ import annotations

from packrecorder.dashboard_metrics import compute_dashboard_metrics


def test_compute_dashboard_metrics_basic() -> None:
    rows = [
        {
            "order_id": "A001",
            "packer": "Máy 1",
            "created_at": "2026-04-16T09:00:00",
            "duration_seconds": 30.0,
            "storage_status": "synced",
            "machine_id": "m1",
            "station_name": "Máy 1",
        },
        {
            "order_id": "A002",
            "packer": "Máy 1",
            "created_at": "2026-04-16T09:01:00",
            "duration_seconds": 45.0,
            "storage_status": "pending_upload",
            "machine_id": "m1",
            "station_name": "Máy 1",
        },
        {
            "order_id": "B001",
            "packer": "Máy 2",
            "created_at": "2026-04-16T10:00:00",
            "duration_seconds": 60.0,
            "storage_status": "local_only",
            "machine_id": "m2",
            "station_name": "Máy 2",
        },
    ]
    m = compute_dashboard_metrics(rows)
    assert m.total_orders == 3
    assert round(m.avg_duration_seconds, 2) == 45.0
    assert m.synced_count == 1
    assert m.pending_sync_count == 2
    assert m.hourly_counts[9] == 2
    assert m.hourly_counts[10] == 1
    assert len(m.by_packer) == 2


def test_compute_dashboard_metrics_empty() -> None:
    m = compute_dashboard_metrics([])
    assert m.total_orders == 0
    assert m.avg_duration_seconds == 0.0
    assert m.hourly_counts == [0] * 24
