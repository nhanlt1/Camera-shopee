# Dual Storage, Heartbeat & Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Thêm lưu video **2 lớp** (Primary = thư mục đồng bộ kiểu Drive, Backup = ổ local), **worker nền** đẩy file từ Backup → Primary khi khả dụng, **SQLite index** + **status.json** (dung lượng ổ backup + **`last_heartbeat`**) để máy phụ biết dữ liệu “tươi” hay trễ, và **UI tìm kiếm** (bảng + lọc) trong app; tuỳ chọn **FastAPI** đọc cùng DB path cho trình duyệt.

**Architecture:** **Local-First (máy đóng gói là gốc):** SQLite index là **nguồn sự thật** trên máy đóng gói — đường dẫn có thể nằm dưới cây Primary (Drive) nhưng vẫn là **ổ cache cục bộ** của client Drive; khi Primary “chết”, máy đóng gói **vẫn ghi DB + video** (video qua Backup, DB qua bản local dự phòng nếu cần — xem ràng buộc SQLite bên dưới). **Máy phụ** chỉ đọc bản DB/JSON đã được đồng bộ qua Drive (hoặc LAN); vì vậy cần **heartbeat** trong `status.json` để không “mù” khi sync trễ. Luồng quay **không đợi** mạng: `build_output_path` vẫn tạo cùng cấu trúc `YYYY-MM-DD/name.mp4`. **Resolver** chọn root ghi (Primary nếu ghi thử OK, ngược lại Backup) và ghi `storage_status = "pending_upload"` khi ghi Backup. **Một writer** index (SQLite) trên máy đóng gói; máy khác **read-only** (`uri=file:...?mode=ro`). **`last_heartbeat`** trong JSON được cập nhật **mỗi ~1 phút và mỗi khi lưu xong một file video** (start hoặc stop tùy chọn — khuyến nghị **sau khi đường dẫn output đã commit** / FFmpeg đóng file). `status.json` ghi trên Primary khi ghi được **và luôn** trên Backup (cùng nội dung) để khi Drive chết văn phòng vẫn có thể đọc heartbeat qua **đường dẫn LAN/SMB tới Backup** (cấu hình `remote_status_json_path` trỏ tới bản trên Primary *hoặc* mirror SMB — document trong settings). Worker nền quét `pending_upload`, `shutil.move` an toàn. UI: `QTableView` + filter; máy phụ: **đèn + thông điệp** theo tuổi của `last_heartbeat` (ngưỡng 2 phút / 5 phút — xem mục dưới).

**Tech Stack:** Python 3.11+, PySide6, `sqlite3` (stdlib), `psutil` (mới), `pathlib`, pytest; tuỳ chọn FastAPI + uvicorn trong `[project.optional-dependencies]`.

**Ràng buộc thực tế:** Google Drive File Stream có thể làm SQLite “busy” — index ưu tiên **một file duy nhất** dưới `video_root/...` với **timeout** dài và **retry**; nếu không ghi được vào đó, ghi **bản local** (`%LOCALAPPDATA%/PackRecorder/recording_index.sqlite`) và set `index_degraded: true` trong JSON để máy phụ biết index trên Drive có thể lệch. WAL không bật trên ổ sync nếu gặp lỗi — `journal_mode=DELETE` mặc định.

**Tóm tắt vai trò:** SQLite (và video) trên máy đóng gói = **bằng chứng đầy đủ**; file JSON có **`last_heartbeat`** = **kiểm tra sự sống / độ tươi** cho máy phụ. Kết hợp hai thứ → biết đang xem dữ liệu tươi hay đang bị trễ.

---

## JSON vs SQLite: tối ưu & SQLite **không** phình vì Heartbeat

**Câu hỏi:** Heartbeat có làm file SQLite **phình (bloat)** không?  
**Trả lời:** **Không** — với điều kiện **không** ghi heartbeat vào SQLite bằng cách **INSERT từng dòng log** mỗi lần nhịp đập.

| Thành phần | Lưu ở đâu | Lý do |
|-----------|-----------|--------|
| Trạng thái hệ thống (**`last_heartbeat`**, dung lượng ổ backup, `index_degraded`, …) | **`status.json`** | File nhẹ, máy phụ chỉ cần đọc text/JSON (không bắt buộc mở DB); dễ đồng bộ Drive; ghi đè toàn file atomic (plan Task 3/6). |
| **Danh mục video** (mã đơn, packer, đường dẫn, `storage_status`, thời điểm) | **SQLite** (`recordings`) | Tìm kiếm/lọc bằng SQL nhanh khi số bản ghi lớn; mỗi video **một INSERT** (đúng nghiệp vụ). |

**Cách sai (gây phình):** Mỗi lần heartbeat `INSERT` một dòng vào bảng kiểu `heartbeat_log` → sau tháng/năm có **hàng trăm nghìn dòng rác**, file `.sqlite` phình và VACUUM tốn kém.

**Cách đúng trong plan này:** Heartbeat **chỉ** cập nhật **`status.json`** (ghi đè object, không tích lũy lịch sử trong DB). SQLite **chỉ** nhận `INSERT` khi **có thêm một bản ghi video** (và `UPDATE` khi sync/move).

**Tuỳ chọn (không bắt buộc):** Nếu sau này muốn **mirror** vài số liệu vào DB (ví dụ báo cáo nội bộ), dùng bảng **`system_status`** **một dòng cố định** (`id = 1`) và **chỉ** `UPDATE`:

```sql
UPDATE system_status
SET last_heartbeat = CURRENT_TIMESTAMP, storage_usage_percent = 85.5
WHERE id = 1;
```

Khởi tạo một lần: `INSERT INTO system_status (id, ...) VALUES (1, ...)` rồi mọi nhịp sau chỉ `UPDATE` — kích thước trang SQLite **không tăng** theo số lần heartbeat. **Khuyến nghị:** Tránh trùng nguồn sự thật — nếu JSON đã là canonical cho máy phụ thì **không cần** bảng `system_status` trong MVP; chỉ thêm khi có lý do tích hợp SQL-only.

**Lưu ý thực tế:** Kích thước file SQLite vẫn tăng theo **số video** (bảng `recordings`); đó là bình thường. Định kỳ `VACUUM` chỉ cần khi đã xóa hàng loạt bản ghi hoặc sau migration — **không** phải hậu quả của heartbeat.

---

## Ngưỡng Heartbeat (máy phụ — bắt buộc theo spec Sang Hà)

Tính `age_seconds = now_local - parsed(last_heartbeat)` (cùng múi giờ; khuyến nghị ISO 8601 local hoặc UTC + trường `last_heartbeat_tz` — tối thiểu parse chuỗi hiện tại trong JSON).

| Điều kiện | Đèn / UI | Thông điệp ngắn (status bar) |
|-----------|----------|------------------------------|
| `age_seconds <= 120` (≤ 2 phút) | Xanh | **Hệ thống đang đồng bộ** |
| `120 < age_seconds <= 300` | Vàng (tuỳ chọn, khuyến nghị) | **Có thể trễ — kiểm tra máy đóng gói / Drive** |
| `age_seconds > 300` (> 5 phút) | Đỏ | **CẢNH BÁO: Mất kết nối với máy đóng gói (có thể do lỗi Drive hoặc mất mạng)** |

Khi mở **tab/dialog tìm kiếm** trên máy phụ trong trạng thái đỏ: hiện `QMessageBox.information` (hoặc banner trong dialog): **Dữ liệu đang bị trễ. Vui lòng kiểm tra máy đóng gói hoặc liên hệ kỹ thuật.**

---

## Kịch bản xử lý khi Drive “sập”

1. **Máy đóng gói:** Resolver không ghi được Primary → ghi video vào Backup; `RecordingIndex.insert(..., storage_status="pending_upload")`; heartbeat vẫn chạy (ưu tiên ghi JSON lên Backup).
2. **Máy văn phòng:** Đọc `status.json` (trên Primary đã map hoặc bản mirror). Nếu chỉ còn bản cũ trên Drive → `last_heartbeat` cũ > 5 phút → đỏ + thông báo trễ; kết quả tìm kiếm từ SQLite có thể **không có bản ghi mới nhất** — đúng kỳ vọng (không “lừa” user).
3. **Khi Primary hoạt động lại:** Client Drive đồng bộ `.db` / video; `BackupSyncWorker` `move` từ Backup → Primary và `mark_synced`; heartbeat trên Primary cập nhật lại → máy phụ thấy xanh và dữ liệu mới.

---

## Quản lý video (retention — tự xóa sau N ngày)

**Hiện trạng codebase:** `main_window._run_retention()` gọi `packrecorder.retention.purge_old_day_folders` với **`keep_days` cố định = 16** — không nằm trong `AppConfig` và không có nhóm cài đặt riêng.

**Mục tiêu plan:** **Di chuyển** cấu hình này vào **`AppConfig`** và hiển thị trong **mục / nhóm UI 「Quản lý video」** trong **`settings_dialog.py`** (ví dụ `QGroupBox` tiêu đề *Quản lý video*), không để số 16 hard-code trong `main_window`.

| Hạng mục | Chi tiết |
|----------|----------|
| Config | `video_retention_keep_days: int = 16` — số ngày **giữ** thư mục theo ngày (`YYYY-MM-DD`) dưới root quay; folder cũ hơn ngưỡng bị xóa (logic hiện có trong `retention.py`). |
| UI | Spin box + nhãn rõ ràng (vd. *“Giữ video tối đa (ngày), sau đó tự xóa thư mục ngày cũ”*), tooltip: chỉ xóa thư mục con của **đường dẫn gốc quay**, không đụng `PackRecorder/` metadata nếu đặt cạnh. |
| Runtime | `_run_retention` đọc `self._config.video_retention_keep_days`. **Dual-path:** nếu `video_backup_root` khác rỗng, gọi `purge_old_day_folders` **lần lượt** cho `Path(video_root)` và `Path(video_backup_root)` cùng `keep_days` (cùng `date.today()`). |
| SQLite | Tuỳ chọn sau: khi xóa folder, có thể `DELETE`/`UPDATE` bản ghi `recordings` trỏ vào file không còn — **không** bắt buộc MVP; tránh orphan paths trong search. |

**Ghi chú:** Timer purge hiện ~3 giờ / lúc khởi động giữ nguyên; chỉ thay nguồn số ngày từ config.

---

## File structure (create / modify)

| Path | Responsibility |
|------|------------------|
| `pyproject.toml` | Thêm dependency `psutil>=5.9`; optional `fastapi`, `uvicorn` |
| `src/packrecorder/config.py` | `video_backup_root`, `status_json_relative`, heartbeat/sync/disk fields (Task 4), **`video_retention_keep_days`** (=16, nhóm Quản lý video) |
| `src/packrecorder/heartbeat_consumer.py` | Hàm thuần `office_heartbeat_state(age_seconds, fresh_s, stale_s) -> (light, short_msg, stale_for_search)` để test không cần Qt |
| `src/packrecorder/storage_resolver.py` | `choose_write_root(primary: Path, backup: Path | None) -> tuple[Path, str]` (`"primary"` \| `"backup"`), `ensure_dir(path) -> bool` |
| `src/packrecorder/recording_index.py` | SQLite **chỉ** danh mục `recordings` (+ optional `system_status` 1 dòng UPDATE — không bắt buộc); **không** bảng log heartbeat |
| `src/packrecorder/status_publish.py` | `build_status_dict(...) -> dict`, `write_status_json(path, data)`, `disk_usage_for_path(path) -> dict` (psutil) |
| `src/packrecorder/sync_worker.py` | `BackupSyncWorker(QThread)` hoặc class tương đương: vòng lặp move + cập nhật index |
| `src/packrecorder/ui/main_window.py` | Timer heartbeat, resolver, đèn máy phụ; **`_run_retention`** dùng `cfg.video_retention_keep_days`, purge **primary + backup root** khi có backup |
| `src/packrecorder/ui/settings_dialog.py` | **`QGroupBox` «Quản lý video»:** spin `video_retention_keep_days`; các ô Backup / heartbeat / disk như task khác |
| `src/packrecorder/ui/recording_search_dialog.py` | Dialog tìm kiếm: filters + table |
| `src/packrecorder/admin_app.py` (optional) | FastAPI: `GET /health`, `GET /recordings?...` đọc SQLite path từ env |
| `tests/test_storage_resolver.py` | |
| `tests/test_recording_index.py` | temp sqlite |
| `tests/test_status_publish.py` | mock psutil hoặc temp dir |
| `tests/test_heartbeat_consumer.py` | ngưỡng 120s / 300s |
| `tests/test_config.py` | (nếu có) round-trip `video_retention_keep_days` |

---

### Task 1: Dependency + `storage_resolver`

**Files:**
- Modify: `pyproject.toml`
- Create: `src/packrecorder/storage_resolver.py`
- Create: `tests/test_storage_resolver.py`

- [x] **Step 1: Add psutil**

```toml
dependencies = [
  ...
  "psutil>=5.9.0",
]
```

- [x] **Step 2: Write failing tests**

```python
# tests/test_storage_resolver.py
from pathlib import Path

from packrecorder.storage_resolver import choose_write_root


def test_backup_none_uses_primary(tmp_path: Path) -> None:
    p = tmp_path / "p"
    p.mkdir()
    root, tag = choose_write_root(p, None)
    assert root == p
    assert tag == "primary"


def test_primary_missing_uses_backup(tmp_path: Path) -> None:
    backup = tmp_path / "b"
    backup.mkdir()
    primary = tmp_path / "missing" / "p"
    root, tag = choose_write_root(primary, backup)
    assert root == backup
    assert tag == "backup"
```

- [x] **Step 3: Run pytest (expect fail)**

Run: `pytest tests/test_storage_resolver.py -v`  
Expected: `ImportError` or no `choose_write_root`.

- [x] **Step 4: Implement**

```python
# src/packrecorder/storage_resolver.py
from __future__ import annotations

from pathlib import Path


def _is_writable_dir(p: Path) -> bool:
    if not p.exists():
        return False
    if not p.is_dir():
        return False
    try:
        probe = p / ".packrecorder_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False


def choose_write_root(primary: Path, backup: Path | None) -> tuple[Path, str]:
    """
    Trả về (root, "primary"|"backup"). Ưu tiên primary nếu thư mục tồn tại và ghi thử được.
    """
    if _is_writable_dir(primary):
        return primary, "primary"
    if backup is not None and _is_writable_dir(backup):
        return backup, "backup"
    primary.mkdir(parents=True, exist_ok=True)
    if _is_writable_dir(primary):
        return primary, "primary"
    if backup is not None:
        backup.mkdir(parents=True, exist_ok=True)
        if _is_writable_dir(backup):
            return backup, "backup"
    raise OSError("Không ghi được vào primary hay backup.")
```

- [x] **Step 5: Run pytest**

Run: `pytest tests/test_storage_resolver.py -v`  
Expected: PASS

- [x] **Step 6: Commit**

```bash
git add pyproject.toml src/packrecorder/storage_resolver.py tests/test_storage_resolver.py
git commit -m "feat: storage resolver primary vs backup"
```

---

### Task 2: `recording_index` SQLite

**Files:**
- Create: `src/packrecorder/recording_index.py`
- Create: `tests/test_recording_index.py`

**Quy tắc chống bloat:** Trong module này **không** thêm bảng `heartbeat_log` hay mọi thứ tương đương (INSERT mỗi phút). Heartbeat + disk chỉ qua **`status.json`** (Task 3/6). Bảng `recordings` chỉ tăng khi có **video mới**.

- [x] **Step 1: Failing test insert + search**

```python
# tests/test_recording_index.py
import sqlite3
from pathlib import Path

from packrecorder.recording_index import RecordingIndex


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
    )
    rows = idx.search(order_substring="ORD")
    idx.close()
    assert len(rows) == 1
    assert rows[0]["order_id"] == "ORD1"
```

- [x] **Step 2: Run pytest — fail**

- [x] **Step 3: Implement module**

```python
# src/packrecorder/recording_index.py
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional


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


@dataclass
class RecordingIndex:
    db_path: Path
    _conn: Optional[sqlite3.Connection] = None

    def connect(self, *, timeout: float = 30.0) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), timeout=timeout)
        self._conn.row_factory = sqlite3.Row
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
```

- [x] **Step 4: Fix test imports + `created_at`**

Trong test, truyền `created_at="2026-04-08T12:00:00"`.

- [x] **Step 5: pytest PASS + commit**

```bash
git add src/packrecorder/recording_index.py tests/test_recording_index.py
git commit -m "feat: SQLite recording index"
```

---

### Task 3: `status_publish` + heartbeat payload

**Files:**
- Create: `src/packrecorder/status_publish.py`
- Create: `tests/test_status_publish.py`

- [x] **Step 1: Test JSON shape (không gọi psutil thật — monkeypatch)**

```python
# tests/test_status_publish.py
from datetime import datetime, timezone
from pathlib import Path

from packrecorder import status_publish as sp


def test_write_roundtrip(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(
        sp,
        "disk_usage_for_path",
        lambda p: {"total_gb": 100.0, "used_gb": 50.0, "free_gb": 50.0, "percent": 50.0},
    )
    out = tmp_path / "status.json"
    d = sp.build_status_payload(
        backup_root=tmp_path,
        heartbeat_iso=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        index_degraded=False,
    )
    sp.write_status_json(out, d)
    assert out.read_text(encoding="utf-8").strip().startswith("{")
```

- [x] **Step 2: Implement**

```python
# src/packrecorder/status_publish.py
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil


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
    if du["percent"] >= 80:
        disk_light = "yellow"
    else:
        disk_light = "green"
    if du["percent"] > 90:
        disk_light = "red"
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
```

**Ghi chú:** Trường **`last_heartbeat`** là **nhịp đập chính**; dùng **một format cố định** (khuyến nghị ISO 8601 local, ví dụ `2026-04-08T08:30:00`) và **cùng parser** ở Task 7.

- [x] **Step 3: pytest + commit**

---

### Task 4: Config + wiring `build_output_path` + index insert

**Files:**
- Modify: `src/packrecorder/config.py`
- Modify: `src/packrecorder/ui/dual_station_widget.py` (backup path field nếu dùng chung form)
- Modify: `src/packrecorder/ui/main_window.py` — `_begin_recording_station` / pip: gọi resolver, sau `rec.start(out)` thành công gọi `RecordingIndex.insert`; **sau khi FFmpeg đóng file / `stop()` thành công** gọi `publish_status_json()` (cùng payload + `last_heartbeat` mới) để heartbeat không chỉ phụ thuộc timer

Fields mới trong `AppConfig`:

```python
video_backup_root: str = ""
status_json_relative: str = "PackRecorder/status.json"
heartbeat_interval_ms: int = 60_000
heartbeat_fresh_seconds: int = 120   # ≤ 2 phút → máy phụ: xanh
heartbeat_stale_seconds: int = 300   # > 5 phút → máy phụ: đỏ
sync_worker_interval_ms: int = 300_000
remote_status_json_path: str = ""    # máy phụ: file JSON cần theo dõi (Drive map hoặc UNC)
office_heartbeat_poll_ms: int = 30_000
disk_warn_percent: float = 80.0
disk_critical_percent: float = 90.0
video_retention_keep_days: int = 16  # mục «Quản lý video» — không hard-code trong main_window
```

Logic: `rel_key = out.relative_to(write_root)` dạng posix cho ổn định; `storage_status = "synced"` nếu tag primary else `"pending_upload"`.

- [x] **Step 1:** Mở `RecordingIndex` tại `Path(video_root) / "PackRecorder" / "recordings.sqlite"` (hoặc chỉ `video_root/recordings.sqlite` — **chọn một** trong commit Task 4 và ghi vào `config.py` docstring).

- [x] **Step 2:** Unit test integration nhỏ: resolver + `build_output_path` mock.

- [x] **Step 3:** Commit.

---

### Task 4b: Quản lý video — cấu hình tự xóa sau N ngày (retention)

**Files:**
- Modify: `src/packrecorder/config.py` — field `video_retention_keep_days: int = 16` (đã liệt kê Task 4; đảm bảo `from_json`/`to_json`/default)
- Modify: `src/packrecorder/ui/settings_dialog.py` — nhóm **`QGroupBox("Quản lý video")`** chứa `QSpinBox` (vd. range 1–365 hoặc 0= tắt nếu `retention` hỗ trợ; hiện `purge_old_day_folders` cần `keep_days >= 0` — dùng min **1** hoặc **0** và document: `0` = không xóa theo ngày nếu implement guard, còn không thì min **1** cho đơn giản)
- Modify: `src/packrecorder/ui/main_window.py` — `_run_retention`: thay literal `16` bằng `self._config.video_retention_keep_days`; nếu `getattr(cfg, "video_backup_root", "")` strip khác rỗng thì `purge_old_day_folders(Path(backup), keep_days, today)` sau primary
- Test: `tests/test_config.py` — load/save default 16; có thể thêm test nhỏ mock `_run_retention` nếu đã có pattern

- [x] **Step 1:** Thêm field vào `AppConfig` + serialization (theo style file hiện tại).

- [x] **Step 2:** Settings: group «Quản lý video» + spin, `apply_to_config` / load từ config.

- [x] **Step 3:** `main_window._run_retention` dùng config + dual root.

- [x] **Step 4:** `pytest tests/test_config.py -v` (và toàn bộ nếu cần).

- [x] **Step 5:** Commit `feat(settings): retention days in Quản lý video group`

---

### Task 5: `BackupSyncWorker`

**Files:**
- Create: `src/packrecorder/sync_worker.py`

- [x] **Implement loop:**
  - Mỗi `sync_worker_interval_ms`, `iter_pending()`.
  - Với mỗi row: `src = Path(resolved_path)`, `dst = Path(primary_root) / rel_key` (dùng `Path` join theo từng phần của `rel_key` split `/`).
  - `dst.parent.mkdir(parents=True, exist_ok=True)`; `shutil.move(str(src), str(dst))` trong `try`; thành công → `mark_synced(row["id"], str(dst))`.

- [x] **Signal** `sync_failed = Signal(str)` để status bar.

- [x] **Start/stop** từ `MainWindow` khi có `video_backup_root` non-empty.

- [x] **Test:** pytest với temp dirs + index row giả.

---

### Task 6: Heartbeat timer + đèn trạng thái (máy đóng gói — publisher)

**Files:**
- Modify: `src/packrecorder/ui/main_window.py`
- Modify: `src/packrecorder/ui/styles.qss` (màu dot)

- [x] Tách hàm `publish_status_json(cfg: AppConfig) -> None`: lấy `datetime.now().isoformat(timespec="seconds")` làm `heartbeat_iso`, `build_status_payload`, ghi **atomic** qua `write_status_json` tới (1) `Path(video_root) / status_json_relative` nếu ghi được, (2) **luôn** `Path(video_backup_root) / status_json_relative` khi `video_backup_root` khác rỗng.

- [x] `QTimer` mỗi `heartbeat_interval_ms` (~1 phút): gọi `publish_status_json`.

- [x] **Thêm:** Gọi `publish_status_json` **mỗi khi lưu xong một file video** (hook `recording_stopped` / `on_ffmpeg_finished` / sau `insert` + file đã close — một lần mỗi file, tránh spam nếu burst).

- [x] `QLabel` trong status bar (publisher): hiển thị **“Publisher OK”** / màu xanh nếu lần ghi JSON backup gần nhất thành công; nếu backup path trống chỉ ghi Primary thì coi OK khi Primary ghi được.

---

### Task 7: Chế độ đọc (máy phụ) — `last_heartbeat` 2 phút / 5 phút

**Files:**
- Create: `src/packrecorder/heartbeat_consumer.py`
- Create: `tests/test_heartbeat_consumer.py`
- Modify: `src/packrecorder/config.py` (đã có `remote_status_json_path`, `heartbeat_fresh_seconds`, `heartbeat_stale_seconds`)
- Modify: `src/packrecorder/ui/main_window.py`

- [x] **Step 1: Test thuần (không Qt)**

```python
# tests/test_heartbeat_consumer.py
from packrecorder.heartbeat_consumer import office_heartbeat_state


def test_green_when_fresh() -> None:
    light, msg, search_stale = office_heartbeat_state(60.0, fresh_s=120, stale_s=300)
    assert light == "green"
    assert "đồng bộ" in msg.lower() or "Đồng bộ" in msg


def test_red_when_stale() -> None:
    light, msg, search_stale = office_heartbeat_state(400.0, fresh_s=120, stale_s=300)
    assert light == "red"
    assert search_stale is True
    assert "CẢNH BÁO" in msg or "mất kết nối" in msg.lower()
```

- [x] **Step 2: Implement**

```python
# src/packrecorder/heartbeat_consumer.py
from __future__ import annotations


def office_heartbeat_state(
    age_seconds: float,
    *,
    fresh_s: int = 120,
    stale_s: int = 300,
) -> tuple[str, str, bool]:
    """
    age_seconds: chênh lệch (now - last_heartbeat), giây, >= 0.
    Trả về (light, status_bar_message, show_search_delay_warning).
    """
    if age_seconds <= fresh_s:
        return ("green", "Hệ thống đang đồng bộ", False)
    if age_seconds <= stale_s:
        return (
            "yellow",
            "Có thể trễ — kiểm tra máy đóng gói hoặc Drive",
            False,
        )
    return (
        "red",
        "CẢNH BÁO: Mất kết nối với máy đóng gói (có thể do lỗi Drive hoặc mất mạng)",
        True,
    )
```

- [x] **Step 3: `MainWindow` (máy phụ):** Nếu `remote_status_json_path` khác rỗng: `QTimer` mỗi `office_heartbeat_poll_ms` đọc JSON, parse `last_heartbeat`, tính `age_seconds`, gọi `office_heartbeat_state(..., fresh_s=cfg.heartbeat_fresh_seconds, stale_s=cfg.heartbeat_stale_seconds)`; cập nhật màu dot + `statusBar().showMessage(msg)`; lưu `search_stale` vào attribute để Task 8 dùng.

- [x] **Step 4: File JSON không tồn tại hoặc parse lỗi:** coi như `age_seconds = +inf` → đỏ + `search_stale = True`.

- [x] **Step 5: pytest + commit**

- [x] **Lưu ý đồng hồ:** Document trong settings: bật đồng bộ thời gian Windows (NTP); nếu hai máy lệch múi giờ, ngưỡng phút sẽ sai.

---

### Task 8: `RecordingSearchDialog`

**Files:**
- Create: `src/packrecorder/ui/recording_search_dialog.py`
- Modify: `src/packrecorder/ui/main_window.py` — menu **Tệp → Tìm kiếm video…**

- [x] `QLineEdit` mã đơn, `QDateEdit` from/to, `QComboBox` trạng thái (`(Tất cả)`, `synced`, `pending_upload`, `local_only`).
- [x] `QPushButton` Tìm → `RecordingIndex.search` (mở DB read-only từ path config giống máy đóng gói hoặc `remote_status_json_path` sibling folder — **document**: DB path = `dirname(status.json)/recordings.sqlite`).

- [x] **Khi mở dialog (máy phụ):** Nếu `MainWindow._office_search_stale` (hoặc tương đương) là `True`, gọi `QMessageBox.information(parent, "Dữ liệu", "Dữ liệu đang bị trễ. Vui lòng kiểm tra máy đóng gói hoặc liên hệ kỹ thuật.")` một lần mỗi lần mở dialog (hoặc chỉ khi stale chuyển từ False→True — chọn một hành vi và giữ nhất quán).

- [x] Double-click row: nếu `storage_status == "synced"` và `primary_root` hợp lệ → `QUrl.fromLocalFile(primary_root / rel_key)`; else → `QUrl.fromLocalFile(resolved_path)`.

- [x] `pytest-qt` optional một smoke `dialog.show()` — có thể bỏ qua nếu CI không có display.

---

### Task 9 (optional): FastAPI `admin_app`

**Files:**
- Create: `src/packrecorder/admin_app.py`
- Modify: `pyproject.toml` optional-deps `admin = ["fastapi>=0.110", "uvicorn>=0.27"]`

```python
# src/packrecorder/admin_app.py — skeleton
import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse

app = FastAPI()
_DB = Path(os.environ.get("PACKRECORDER_INDEX_DB", ""))


@app.get("/api/health")
def health() -> JSONResponse:
    ok = _DB.is_file()
    return JSONResponse({"index_db_ok": ok})


@app.get("/api/recordings")
def recordings(q: str = "", limit: int = 100) -> JSONResponse:
    from packrecorder.recording_index import RecordingIndex

    idx = RecordingIndex(_DB)
    idx.connect()
    rows = idx.search(order_substring=q)[:limit]
    idx.close()
    return JSONResponse({"items": rows})
```

- [x] Chạy: `PACKRECORDER_INDEX_DB=Z:/.../recordings.sqlite uvicorn packrecorder.admin_app:app --port 8765`

- [x] Commit riêng: `feat: optional FastAPI admin read API`

---

## Self-review (checklist)

| Yêu cầu spec | Task |
|-------------|------|
| Local-First: máy đóng gói luôn có DB + video, tìm được local | Architecture + Task 4 + ràng buộc SQLite |
| Ghi Primary, lỗi → Backup + `pending_upload` | Task 1 + 4 |
| Worker move Backup → Primary → `synced` | Task 5 |
| JSON + `last_heartbeat` + disk | Task 3 + 6 |
| Heartbeat mỗi ~1 phút **và** khi lưu video | Task 6 |
| Máy phụ: ≤2 phút xanh, >5 phút đỏ + cảnh báo | Task 7 |
| Mở tìm kiếm: thông báo “dữ liệu trễ” khi stale | Task 8 |
| Kịch bản Drive sập / hồi phục | Mục “Kịch bản…” + Task 4–6 |
| JSON = heartbeat/trạng thái; SQLite = danh mục video; không INSERT log heartbeat | Mục “JSON vs SQLite…” + Task 2 note |
| Tự xóa video sau 16 ngày (cấu hình) trong **Quản lý video** | Mục “Quản lý video” + Task 4b |
| Bảng tìm kiếm + lọc + link | Task 8 |
| FastAPI tùy chọn | Task 9 |

**Placeholder scan:** Không dùng TBD trong bước triển khai — chỗ “chọn một” đường dẫn DB cần **quyết định trong Task 4 commit** và ghi vào `config.py` docstring.

**Kiểu thống nhất:** `storage_status` chỉ dùng `synced` | `pending_upload` | `local_only` xuyên suốt.

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-08-dual-storage-heartbeat-search.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — Một subagent mỗi task, review giữa các task.

**2. Inline Execution** — Làm tuần tự trong session với executing-plans và checkpoint.

**Bạn muốn theo hướng nào?**
