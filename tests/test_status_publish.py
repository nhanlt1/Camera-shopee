from datetime import datetime, timezone
from pathlib import Path

from packrecorder import status_publish as sp


def test_write_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        sp,
        "disk_usage_for_path",
        lambda p: {
            "total_gb": 100.0,
            "used_gb": 50.0,
            "free_gb": 50.0,
            "percent": 50.0,
        },
    )
    out = tmp_path / "status.json"
    d = sp.build_status_payload(
        backup_root=tmp_path,
        heartbeat_iso=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S"),
        index_degraded=False,
    )
    sp.write_status_json(out, d)
    assert out.read_text(encoding="utf-8").strip().startswith("{")
