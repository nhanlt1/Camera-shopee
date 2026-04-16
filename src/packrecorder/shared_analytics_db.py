from __future__ import annotations

import hashlib
from pathlib import Path

from packrecorder.config import AppConfig
from packrecorder.recording_index import RecordingIndex


def shared_analytics_db_path(cfg: AppConfig) -> Path | None:
    video_root = (cfg.video_root or "").strip()
    if not video_root:
        return None
    software_id = (cfg.software_id or "").strip() or "default"
    root_rel = (cfg.analytics_shared_root_relative or "").strip() or "PackRecorder/analytics"
    return Path(video_root) / root_rel / software_id / "analytics.sqlite"


def make_record_uid(
    *,
    machine_id: str,
    station_name: str,
    order_id: str,
    created_at: str,
    rel_key: str,
) -> str:
    raw = "||".join(
        [
            machine_id.strip(),
            station_name.strip(),
            order_id.strip(),
            created_at.strip(),
            rel_key.strip(),
        ]
    )
    return hashlib.sha1(raw.encode("utf-8", errors="ignore")).hexdigest()


def append_shared_analytics_record(
    cfg: AppConfig,
    *,
    order_id: str,
    packer: str,
    station_name: str,
    rel_key: str,
    storage_status: str,
    primary_root: str,
    backup_root: str | None,
    resolved_path: str,
    created_at: str,
    duration_seconds: float,
) -> bool:
    db_path = shared_analytics_db_path(cfg)
    if db_path is None:
        return False
    db_path.parent.mkdir(parents=True, exist_ok=True)
    idx = RecordingIndex(db_path)
    idx.connect(timeout=10.0)
    try:
        uid = make_record_uid(
            machine_id=cfg.machine_id,
            station_name=station_name,
            order_id=order_id,
            created_at=created_at,
            rel_key=rel_key,
        )
        return idx.insert_ignore_duplicate(
            order_id=order_id,
            packer=packer,
            software_id=cfg.software_id,
            machine_id=cfg.machine_id,
            station_name=station_name,
            record_uid=uid,
            rel_key=rel_key,
            storage_status=storage_status,
            primary_root=primary_root,
            backup_root=backup_root,
            resolved_path=resolved_path,
            created_at=created_at,
            duration_seconds=duration_seconds,
        )
    finally:
        idx.close()
