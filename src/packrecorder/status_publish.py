from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import psutil

from packrecorder.config import AppConfig


def disk_usage_for_path(path: Path) -> dict[str, float]:
    p = str(path.resolve())
    u = psutil.disk_usage(p)
    gb = 1024**3
    return {
        "total_gb": round(u.total / gb, 2),
        "used_gb": round(u.used / gb, 2),
        "free_gb": round(u.free / gb, 2),
        "percent": float(u.percent),
    }


def build_status_payload(
    *,
    backup_root: Path,
    heartbeat_iso: str,
    index_degraded: bool,
    warn_percent: float = 90.0,
) -> dict[str, Any]:
    du = disk_usage_for_path(backup_root)
    st = "Warning" if du["percent"] > warn_percent else "OK"
    if du["percent"] > 90:
        disk_light = "red"
    elif du["percent"] >= 80:
        disk_light = "yellow"
    else:
        disk_light = "green"
    return {
        "disk": du,
        "disk_ui": disk_light,
        "last_heartbeat": heartbeat_iso,
        "index_degraded": index_degraded,
        "status": st,
    }


def write_status_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def status_json_paths(cfg: AppConfig) -> tuple[Path | None, Path | None]:
    """(primary_path_or_none, backup_path_or_none) — relative từ từng root."""
    rel = (cfg.status_json_relative or "PackRecorder/status.json").strip().lstrip("\\/")
    if not rel:
        rel = "PackRecorder/status.json"
    primary: Path | None = None
    if (cfg.video_root or "").strip():
        primary = Path(cfg.video_root) / rel
    backup: Path | None = None
    if (cfg.video_backup_root or "").strip():
        backup = Path(cfg.video_backup_root) / rel
    return primary, backup


def publish_status_json(cfg: AppConfig, *, index_degraded: bool) -> tuple[bool, bool]:
    """
    Ghi status.json lên primary (nếu có root) và backup (nếu có).
    Trả về (primary_ok, backup_ok).
    """
    from datetime import datetime

    heartbeat_iso = datetime.now().isoformat(timespec="seconds")
    br = (cfg.video_backup_root or "").strip()
    vr = (cfg.video_root or "").strip()
    backup_root = Path(br) if br else (Path(vr) if vr else Path("."))
    try:
        backup_root.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    payload = build_status_payload(
        backup_root=backup_root,
        heartbeat_iso=heartbeat_iso,
        index_degraded=index_degraded,
        warn_percent=float(cfg.disk_critical_percent),
    )
    primary_p, backup_p = status_json_paths(cfg)
    primary_ok = True
    backup_ok = True
    if primary_p is not None:
        try:
            write_status_json(primary_p, payload)
        except OSError:
            primary_ok = False
    if backup_p is not None:
        try:
            write_status_json(backup_p, payload)
        except OSError:
            backup_ok = False
    return primary_ok, backup_ok
