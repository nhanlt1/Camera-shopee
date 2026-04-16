from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from packrecorder.config import AppConfig

_SCHEMA = """
CREATE TABLE IF NOT EXISTS recordings (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  order_id TEXT NOT NULL,
  packer TEXT NOT NULL,
  software_id TEXT NOT NULL DEFAULT 'default',
  machine_id TEXT NOT NULL DEFAULT '',
  station_name TEXT NOT NULL DEFAULT '',
  record_uid TEXT NOT NULL DEFAULT '',
  rel_key TEXT NOT NULL,
  storage_status TEXT NOT NULL,
  primary_root TEXT NOT NULL,
  backup_root TEXT,
  resolved_path TEXT NOT NULL,
  created_at TEXT NOT NULL,
  synced_at TEXT,
  duration_seconds REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_recordings_order ON recordings(order_id);
CREATE INDEX IF NOT EXISTS idx_recordings_status ON recordings(storage_status);
"""


def preferred_index_path(cfg: AppConfig) -> Path:
    return Path(cfg.video_root) / "PackRecorder" / "recordings.sqlite"


def fallback_index_path() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    base = Path(local) if local else Path.home()
    return base / "PackRecorder" / "recording_index.sqlite"


def recordings_db_path_for_search(cfg: AppConfig) -> Path | None:
    """
    File SQLite để đọc danh sách ghi (tìm kiếm): trùng file app đang ghi.

    - Có video_root: ưu tiên .../PackRecorder/recordings.sqlite, nếu chưa có file thì
      dùng fallback LOCALAPPDATA (cùng chỗ open_recording_index ghi khi không tạo được ổ chính).
    - Không video_root: app ghi vào fallback (open_recording_index không dùng remote để ghi);
      đọc fallback trước; nếu chưa có thì thử recordings.sqlite cạnh remote_status_json (máy xem bản sao).
    """
    if (cfg.video_root or "").strip():
        primary = preferred_index_path(cfg)
        if primary.is_file():
            return primary
        fb = fallback_index_path()
        if fb.is_file():
            return fb
        return None
    fb0 = fallback_index_path()
    if fb0.is_file():
        return fb0
    r = (cfg.remote_status_json_path or "").strip()
    if r:
        p = Path(r).parent / "recordings.sqlite"
        if p.is_file():
            return p
    return None


def open_recording_index(cfg: AppConfig) -> tuple["RecordingIndex", bool]:
    """
    Mở DB ghi ưu tiên dưới video_root/PackRecorder; nếu lỗi thì fallback LOCALAPPDATA.
    Trả về (index, index_degraded).
    """
    last_err: OSError | None = None
    if (cfg.video_root or "").strip():
        p = preferred_index_path(cfg)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            idx = RecordingIndex(p)
            idx.connect()
            return idx, False
        except OSError as e:
            last_err = e
    fb = fallback_index_path()
    try:
        fb.parent.mkdir(parents=True, exist_ok=True)
        idx = RecordingIndex(fb)
        idx.connect()
        return idx, True
    except OSError as e:
        last_err = e
    if last_err:
        raise last_err
    raise OSError("Cannot open recording index")


@dataclass
class RecordingIndex:
    db_path: Path
    _conn: Optional[sqlite3.Connection] = None

    def connect(self, *, timeout: float = 30.0, uri_readonly: bool = False) -> None:
        if not uri_readonly:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if uri_readonly:
            uri = self.db_path.resolve().as_uri() + "?mode=ro"
            self._conn = sqlite3.connect(uri, uri=True, timeout=timeout)
        else:
            self._conn = sqlite3.connect(str(self.db_path), timeout=timeout)
        self._conn.row_factory = sqlite3.Row
        if not uri_readonly:
            self._conn.executescript(_SCHEMA)
            self._ensure_schema_migrations()

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def insert(
        self,
        *,
        order_id: str,
        packer: str,
        software_id: str = "default",
        machine_id: str = "",
        station_name: str = "",
        record_uid: str = "",
        rel_key: str,
        storage_status: str,
        primary_root: str,
        backup_root: str | None,
        resolved_path: str,
        created_at: str,
        duration_seconds: float = 0.0,
    ) -> None:
        assert self._conn
        self._conn.execute(
            """INSERT INTO recordings
            (order_id, packer, software_id, machine_id, station_name, record_uid, rel_key, storage_status, primary_root, backup_root, resolved_path, created_at, duration_seconds)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                order_id,
                packer,
                software_id or "default",
                machine_id or "",
                station_name or "",
                record_uid or "",
                rel_key,
                storage_status,
                primary_root,
                backup_root or "",
                resolved_path,
                created_at,
                float(max(0.0, duration_seconds)),
            ),
        )
        self._conn.commit()

    def insert_ignore_duplicate(
        self,
        *,
        order_id: str,
        packer: str,
        software_id: str = "default",
        machine_id: str = "",
        station_name: str = "",
        record_uid: str,
        rel_key: str,
        storage_status: str,
        primary_root: str,
        backup_root: str | None,
        resolved_path: str,
        created_at: str,
        duration_seconds: float = 0.0,
    ) -> bool:
        assert self._conn
        cur = self._conn.execute(
            """INSERT OR IGNORE INTO recordings
            (order_id, packer, software_id, machine_id, station_name, record_uid, rel_key, storage_status, primary_root, backup_root, resolved_path, created_at, duration_seconds)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                order_id,
                packer,
                software_id or "default",
                machine_id or "",
                station_name or "",
                record_uid,
                rel_key,
                storage_status,
                primary_root,
                backup_root or "",
                resolved_path,
                created_at,
                float(max(0.0, duration_seconds)),
            ),
        )
        self._conn.commit()
        return int(cur.rowcount or 0) > 0

    def delete_by_id(self, row_id: int) -> None:
        assert self._conn
        self._conn.execute("DELETE FROM recordings WHERE id=?", (int(row_id),))
        self._conn.commit()

    def mark_synced(self, row_id: int, new_resolved_path: str) -> None:
        assert self._conn
        from datetime import datetime

        self._conn.execute(
            "UPDATE recordings SET storage_status=?, resolved_path=?, synced_at=? WHERE id=?",
            ("synced", new_resolved_path, datetime.now().isoformat(timespec="seconds"), row_id),
        )
        self._conn.commit()

    def iter_pending(self) -> list[sqlite3.Row]:
        assert self._conn
        cur = self._conn.execute(
            "SELECT * FROM recordings WHERE storage_status IN ('local_only','pending_upload') ORDER BY id"
        )
        return list(cur.fetchall())

    def search(
        self,
        *,
        order_substring: str = "",
        date_from: str | None = None,
        date_to: str | None = None,
        storage_status: str | None = None,
        storage_status_in: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        assert self._conn
        q = "SELECT * FROM recordings WHERE 1=1"
        args: list[Any] = []
        if order_substring:
            q += " AND (order_id LIKE ? OR packer LIKE ?)"
            like = f"%{order_substring}%"
            args.extend([like, like])
        if date_from:
            q += " AND created_at >= ?"
            args.append(date_from)
        if date_to:
            q += " AND created_at <= ?"
            args.append(date_to)
        if storage_status_in:
            ph = ",".join("?" * len(storage_status_in))
            q += f" AND storage_status IN ({ph})"
            args.extend(storage_status_in)
        elif storage_status:
            q += " AND storage_status = ?"
            args.append(storage_status)
        q += " ORDER BY created_at DESC LIMIT 500"
        cur = self._conn.execute(q, args)
        return [dict(r) for r in cur.fetchall()]

    def search_dashboard(
        self,
        *,
        date_from: str,
        date_to: str,
        software_id: str | None = None,
        packer: str | None = None,
        machine_id: str | None = None,
        station_name: str | None = None,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        assert self._conn
        q = "SELECT * FROM recordings WHERE created_at >= ? AND created_at <= ?"
        args: list[Any] = [date_from, date_to]
        if software_id:
            q += " AND software_id = ?"
            args.append(software_id)
        if packer:
            q += " AND packer = ?"
            args.append(packer)
        if machine_id:
            q += " AND machine_id = ?"
            args.append(machine_id)
        if station_name:
            q += " AND station_name = ?"
            args.append(station_name)
        q += " ORDER BY created_at DESC LIMIT ?"
        args.append(max(50, min(20000, int(limit))))
        cur = self._conn.execute(q, args)
        return [dict(r) for r in cur.fetchall()]

    def distinct_packers(
        self,
        *,
        date_from: str,
        date_to: str,
        software_id: str | None = None,
    ) -> list[str]:
        assert self._conn
        q = "SELECT DISTINCT packer FROM recordings WHERE created_at >= ? AND created_at <= ?"
        args: list[Any] = [date_from, date_to]
        if software_id:
            q += " AND software_id = ?"
            args.append(software_id)
        q += " ORDER BY packer ASC"
        cur = self._conn.execute(q, args)
        return [str(r[0]) for r in cur.fetchall() if str(r[0] or "").strip()]

    def _ensure_schema_migrations(self) -> None:
        """Add missing columns for old DB files without destructive migrations."""
        assert self._conn
        cur = self._conn.execute("PRAGMA table_info(recordings)")
        cols = {str(r["name"]) for r in cur.fetchall()}
        if "software_id" not in cols:
            self._conn.execute(
                "ALTER TABLE recordings ADD COLUMN software_id TEXT NOT NULL DEFAULT 'default'"
            )
        if "machine_id" not in cols:
            self._conn.execute(
                "ALTER TABLE recordings ADD COLUMN machine_id TEXT NOT NULL DEFAULT ''"
            )
        if "station_name" not in cols:
            self._conn.execute(
                "ALTER TABLE recordings ADD COLUMN station_name TEXT NOT NULL DEFAULT ''"
            )
        if "record_uid" not in cols:
            self._conn.execute(
                "ALTER TABLE recordings ADD COLUMN record_uid TEXT NOT NULL DEFAULT ''"
            )
        if "duration_seconds" not in cols:
            self._conn.execute(
                "ALTER TABLE recordings ADD COLUMN duration_seconds REAL NOT NULL DEFAULT 0"
            )
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_recordings_software_created ON recordings(software_id, created_at)"
        )
        self._conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_recordings_record_uid ON recordings(record_uid) WHERE record_uid <> ''"
        )
        self._conn.commit()
