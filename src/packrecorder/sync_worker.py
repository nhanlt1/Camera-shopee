from __future__ import annotations

import shutil
import time
from pathlib import Path

from PySide6.QtCore import QThread, Signal

from packrecorder.recording_index import RecordingIndex


class BackupSyncWorker(QThread):
    """Luồng riêng: mở SQLite riêng để tránh dùng chung connection với UI thread."""

    sync_failed = Signal(str)

    def __init__(
        self,
        db_path: Path,
        interval_ms: int,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._db_path = db_path
        self._interval_ms = max(5_000, int(interval_ms))
        self._stop = False

    def stop_worker(self) -> None:
        self._stop = True

    def run(self) -> None:
        while not self._stop:
            idx = RecordingIndex(self._db_path)
            try:
                idx.connect()
                self._run_once(idx)
            except Exception as e:  # noqa: BLE001
                self.sync_failed.emit(str(e))
            finally:
                idx.close()
            for _ in range(self._interval_ms // 500):
                if self._stop:
                    break
                time.sleep(0.5)

    def _run_once(self, index: RecordingIndex) -> None:
        rows = index.iter_pending()
        for row in rows:
            if self._stop:
                break
            src = Path(row["resolved_path"])
            if not src.is_file():
                continue
            primary = Path(row["primary_root"])
            rel_key = row["rel_key"].replace("\\", "/")
            dst = primary.joinpath(*rel_key.split("/"))
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.move(str(src), str(dst))
            except OSError as e:
                self.sync_failed.emit(f"{src} -> {dst}: {e}")
                continue
            index.mark_synced(int(row["id"]), str(dst))
