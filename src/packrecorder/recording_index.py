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
  rel_key TEXT NOT NULL,
  storage_status TEXT NOT NULL,
  primary_root TEXT NOT NULL,
  backup_root TEXT,
  resolved_path TEXT NOT NULL,
  created_at TEXT NOT NULL,
  synced_at TEXT
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

    def close(self) -> None:
        if self._conn:
            self._conn.close()
            self._conn = None

    def insert(
        self,
        *,
        order_id: str,
        packer: str,
        rel_key: str,
        storage_status: str,
        primary_root: str,
        backup_root: str | None,
        resolved_path: str,
        created_at: str,
    ) -> None:
        assert self._conn
        self._conn.execute(
            """INSERT INTO recordings
            (order_id, packer, rel_key, storage_status, primary_root, backup_root, resolved_path, created_at)
            VALUES (?,?,?,?,?,?,?,?)""",
            (
                order_id,
                packer,
                rel_key,
                storage_status,
                primary_root,
                backup_root or "",
                resolved_path,
                created_at,
            ),
        )
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
        if storage_status:
            q += " AND storage_status = ?"
            args.append(storage_status)
        q += " ORDER BY created_at DESC LIMIT 500"
        cur = self._conn.execute(q, args)
        return [dict(r) for r in cur.fetchall()]
