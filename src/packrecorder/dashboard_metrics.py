from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class DashboardMetrics:
    total_orders: int
    avg_duration_seconds: float
    avg_idle_seconds: float
    pending_sync_count: int
    synced_count: int
    total_size_gb: float
    hourly_counts: list[int]
    by_packer: list[dict[str, Any]]
    detail_rows: list[dict[str, Any]]


def _parse_created_at(row: dict[str, Any]) -> datetime | None:
    raw = str(row.get("created_at") or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def compute_dashboard_metrics(rows: list[dict[str, Any]]) -> DashboardMetrics:
    sorted_rows = sorted(
        rows, key=lambda r: str(r.get("created_at") or ""), reverse=False
    )
    total_orders = len(sorted_rows)
    if total_orders == 0:
        return DashboardMetrics(
            total_orders=0,
            avg_duration_seconds=0.0,
            avg_idle_seconds=0.0,
            pending_sync_count=0,
            synced_count=0,
            total_size_gb=0.0,
            hourly_counts=[0] * 24,
            by_packer=[],
            detail_rows=[],
        )
    durations: list[float] = []
    pending_sync_count = 0
    synced_count = 0
    total_size_bytes = 0
    hourly_counts = [0] * 24
    by_packer_stats: dict[str, dict[str, float]] = {}
    last_time_by_packer: dict[str, datetime] = {}
    idle_gaps: list[float] = []
    detail_rows: list[dict[str, Any]] = []

    for row in sorted_rows:
        packer = str(row.get("packer") or "").strip() or "Chưa rõ"
        duration = float(row.get("duration_seconds") or 0.0)
        durations.append(max(0.0, duration))
        dt = _parse_created_at(row)
        if dt is not None:
            hourly_counts[dt.hour] += 1
            prev = last_time_by_packer.get(packer)
            if prev is not None:
                gap = max(0.0, (dt - prev).total_seconds())
                idle_gaps.append(gap)
            last_time_by_packer[packer] = dt
        status = str(row.get("storage_status") or "")
        if status == "synced":
            synced_count += 1
        elif status in ("local_only", "pending_upload"):
            pending_sync_count += 1
        resolved_path = str(row.get("resolved_path") or "").strip()
        if resolved_path:
            p = Path(resolved_path)
            if p.is_file():
                try:
                    total_size_bytes += int(p.stat().st_size)
                except OSError:
                    pass
        pk = by_packer_stats.setdefault(
            packer, {"count": 0.0, "duration_sum": 0.0, "machine_count": 0.0}
        )
        pk["count"] += 1.0
        pk["duration_sum"] += max(0.0, duration)
        detail_rows.append(
            {
                "order_id": str(row.get("order_id") or ""),
                "packer": packer,
                "created_at": str(row.get("created_at") or ""),
                "duration_seconds": max(0.0, duration),
                "storage_status": status,
                "machine_id": str(row.get("machine_id") or ""),
                "station_name": str(row.get("station_name") or ""),
            }
        )

    by_packer: list[dict[str, Any]] = []
    for packer, stats in by_packer_stats.items():
        c = max(1.0, float(stats["count"]))
        by_packer.append(
            {
                "packer": packer,
                "count": int(stats["count"]),
                "avg_duration_seconds": float(stats["duration_sum"]) / c,
            }
        )
    by_packer.sort(key=lambda x: (-int(x["count"]), str(x["packer"])))
    detail_rows.sort(key=lambda r: str(r["created_at"]), reverse=True)
    return DashboardMetrics(
        total_orders=total_orders,
        avg_duration_seconds=sum(durations) / max(1, len(durations)),
        avg_idle_seconds=sum(idle_gaps) / max(1, len(idle_gaps)),
        pending_sync_count=pending_sync_count,
        synced_count=synced_count,
        total_size_gb=float(total_size_bytes) / (1024.0**3),
        hourly_counts=hourly_counts,
        by_packer=by_packer,
        detail_rows=detail_rows,
    )
