# Pack Video Recorder (MVP) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a Windows 64-bit desktop app (Python 3.11+, PySide6) that records one HD camera to dated folders, names files with **order id + packer label** (settings default/preset **Máy 1** / **Máy 2**), drives recording via scanned order codes (1D+QR from camera frames), enforces duplicate-order UI + long beep, retention (16 days), scheduled shutdown with 60s scan-to-cancel, FFmpeg child cleanup via Job Object, and speaker fallback beep patterns per spec `docs/superpowers/specs/2026-04-06-pack-video-recorder-design.md`.

**Architecture:** Pure-Python domain modules (`paths`, `order_state`, `duplicate`, `retention`, `shutdown_scheduler`) are tested with pytest. UI (`PySide6`) orchestrates a `ScanWorker` (`QThread` + OpenCV + pyzbar) and a `RecordingSession` that owns **one** camera path: **OpenCV reads BGR frames** and pipes raw video into **FFmpeg** (`libx264`, `-an`) so the camera is not double-opened by FFmpeg dshow and OpenCV simultaneously (common Windows failure mode). Optional **keyboard-wedge** barcode path can be added later as a plugin; MVP follows spec camera decode. `windows_job.py` attaches FFmpeg PID to a Win32 Job Object so parent exit kills the child. Sounds: `FeedbackPlayer` uses `QSoundEffect` WAV triplets (short / double short / long) when scanner host API is absent (stub `ScannerHostBeep` no-op for MVP).

**Tech Stack:** Python 3.11+, PySide6, OpenCV-Python, pyzbar (+ ZBar DLL on PATH or bundled), FFmpeg static CLI beside executable, pytest, pytest-qt (optional), `ctypes` for Job Object.

---

## File structure (create/modify)

| Path | Responsibility |
|------|------------------|
| `pyproject.toml` | deps, `[project.scripts] packrecorder = packrecorder.__main__:main` |
| `src/packrecorder/__init__.py` | version |
| `src/packrecorder/__main__.py` | `main()` entry |
| `src/packrecorder/app.py` | `QApplication`, Fusion style, load QSS, `MainWindow` |
| `src/packrecorder/config.py` | `AppConfig` … **`packer_label`** default `"Máy 1"` |
| `src/packrecorder/paths.py` | `sanitize_order_id`, `sanitize_packer_label` (spaces→`-`, same invalid rules), `build_output_path(..., packer_raw, ...)` → `{maDon}_{packer}_{stamp}.mp4` |
| `src/packrecorder/duplicate.py` | `is_duplicate_order(root: Path, order_id: str, today: date) -> bool` |
| `src/packrecorder/retention.py` | `purge_old_day_folders(root: Path, keep_days: int, today: date) -> list[Path]` |
| `src/packrecorder/order_state.py` | pure transitions + `TransitionResult` (start/stop/switch + flags for duplicate check, sounds) |
| `src/packrecorder/shutdown_scheduler.py` | `compute_initial_next_shutdown`, `defer_one_hour` |
| `src/packrecorder/windows_job.py` | `assign_process_to_job_object(pid: int) -> None` |
| `src/packrecorder/ffmpeg_pipe_recorder.py` | start/stop FFmpeg subprocess, rawvideo stdin, Job attach |
| `src/packrecorder/scan_worker.py` | `QThread`, capture, pyzbar, debounce, `barcode_decoded` signal |
| `src/packrecorder/feedback_sound.py` | `FeedbackPlayer` short / double / long |
| `src/packrecorder/scanner_host_beep.py` | `ScannerHostBeep` ABC + `NullScannerHostBeep` |
| `src/packrecorder/ui/main_window.py` | status chips, status bar messages, wire state machine |
| `src/packrecorder/ui/settings_dialog.py` | root path, camera index, **packer combo** (preset **Máy 1**, **Máy 2**, editable), times, toggles |
| `src/packrecorder/ui/countdown_dialog.py` | 60s, scan cancel, `scan_cancelled` signal |
| `src/packrecorder/ui/styles.qss` | Material-like light theme |
| `resources/sounds/README.txt` | instruct to add WAV or use generated |
| `tests/test_paths.py` | |
| `tests/test_duplicate.py` | |
| `tests/test_retention.py` | |
| `tests/test_order_state.py` | |
| `tests/test_shutdown_scheduler.py` | |
| `tests/test_ffmpeg_pipe_recorder.py` | mock `subprocess.Popen` |

**Giai đoạn 2** (PIP hai nguồn): tách plan sau — không nằm trong file này.

---

### Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/packrecorder/__init__.py`
- Create: `src/packrecorder/__main__.py`

- [ ] **Step 1: Add `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=61"]
build-backend = "setuptools.build_meta"

[project]
name = "packrecorder"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
  "PySide6>=6.6.0",
  "opencv-python>=4.9.0",
  "pyzbar>=0.1.9",
  "numpy>=1.26.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-qt>=4.4"]

[project.scripts]
packrecorder = "packrecorder.__main__:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: Create package marker**

```python
# src/packrecorder/__init__.py
__version__ = "0.1.0"
```

- [ ] **Step 3: Stub entrypoint**

```python
# src/packrecorder/__main__.py
import sys

def main() -> None:
    print("packrecorder: run app.py in Task 10", file=sys.stderr)
    raise SystemExit(1)

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Install editable**

Run: `cd c:\Users\nhanl\Documents\Camera-shopee && pip install -e ".[dev]"`

Expected: exit code 0.

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/packrecorder/__init__.py src/packrecorder/__main__.py
git commit -m "chore: scaffold packrecorder package"
```

---

### Task 2: paths — sanitize and output filename

**Files:**
- Create: `src/packrecorder/paths.py`
- Create: `tests/test_paths.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_paths.py
from datetime import datetime
from pathlib import Path

from packrecorder.paths import (
    build_output_path,
    sanitize_order_id,
    sanitize_packer_label,
)


def test_sanitize_replaces_invalid_chars_and_underscore():
    assert sanitize_order_id("a/b<c>") == "a-b-c-"
    assert sanitize_order_id("ORD_001") == "ORD-001"


def test_sanitize_packer_spaces_underscore():
    assert sanitize_packer_label("Máy 1") == "Máy-1"
    assert sanitize_packer_label("Máy 2") == "Máy-2"
    assert sanitize_packer_label("A_B C") == "A-B-C"


def test_build_output_path_includes_packer():
    root = Path("D:/root")
    dt = datetime(2026, 4, 6, 14, 30, 0)
    p = build_output_path(root, "ORD001", "Máy 1", dt)
    assert p == Path("D:/root/2026-04-06/ORD001_Máy-1_20260406-143000.mp4")
```

- [ ] **Step 2: Run test — expect FAIL**

Run: `pytest tests/test_paths.py -v`

Expected: `ModuleNotFoundError` or import error for `paths`.

- [ ] **Step 3: Implement**

```python
# src/packrecorder/paths.py
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path

_INVALID = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_order_id(raw: str) -> str:
    s = raw.strip()
    s = _INVALID.sub("-", s)
    s = s.replace("_", "-")
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "ORDER"


def sanitize_packer_label(raw: str) -> str:
    s = raw.strip()
    s = _INVALID.sub("-", s)
    s = s.replace("_", "-")
    s = s.replace(" ", "-")
    s = re.sub(r"-{2,}", "-", s).strip("-")
    return s or "Máy-1"


def day_folder_name(d: date) -> str:
    return d.isoformat()


def build_output_path(
    root: Path, order_id_raw: str, packer_raw: str, when: datetime
) -> Path:
    oid = sanitize_order_id(order_id_raw)
    pk = sanitize_packer_label(packer_raw)
    day = day_folder_name(when.date())
    stamp = when.strftime("%Y%m%d-%H%M%S")
    return root / day / f"{oid}_{pk}_{stamp}.mp4"
```

- [ ] **Step 4: Run test — expect PASS**

Run: `pytest tests/test_paths.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/packrecorder/paths.py tests/test_paths.py
git commit -m "feat(paths): packer label in filename Máy-1 Máy-2 pattern"
```

---

### Task 3: duplicate detection

**Files:**
- Create: `src/packrecorder/duplicate.py`
- Create: `tests/test_duplicate.py`

- [ ] **Step 1: Failing test with tmp_path**

```python
# tests/test_duplicate.py
from datetime import date
from pathlib import Path

from packrecorder.duplicate import is_duplicate_order
from packrecorder.paths import sanitize_order_id


def test_duplicate_when_prefix_exists(tmp_path: Path):
    root = tmp_path
    day = date(2026, 4, 6)
    day_dir = root / day.isoformat()
    day_dir.mkdir(parents=True)
    oid = sanitize_order_id("DON1")
    (day_dir / f"{oid}_Máy-1_20260406-120000.mp4").write_bytes(b"")
    assert is_duplicate_order(root, "DON1", day) is True


def test_not_duplicate_empty_day(tmp_path: Path):
    root = tmp_path
    day = date(2026, 4, 6)
    (root / day.isoformat()).mkdir(parents=True)
    assert is_duplicate_order(root, "NEW", day) is False
```

- [ ] **Step 2: Run pytest — FAIL**

Run: `pytest tests/test_duplicate.py -v`

- [ ] **Step 3: Implement**

```python
# src/packrecorder/duplicate.py
from __future__ import annotations

from datetime import date
from pathlib import Path

from packrecorder.paths import sanitize_order_id


def is_duplicate_order(root: Path, order_id_raw: str, today: date) -> bool:
    oid = sanitize_order_id(order_id_raw)
    day_dir = root / today.isoformat()
    if not day_dir.is_dir():
        return False
    pattern = f"{oid}_*.mp4"
    return any(day_dir.glob(pattern))
```

- [ ] **Step 4: PASS**

Run: `pytest tests/test_duplicate.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/packrecorder/duplicate.py tests/test_duplicate.py
git commit -m "feat(duplicate): detect existing mp4 prefix for order"
```

---

### Task 4: retention purge

**Files:**
- Create: `src/packrecorder/retention.py`
- Create: `tests/test_retention.py`

- [ ] **Step 1: Test**

```python
# tests/test_retention.py
from datetime import date
from pathlib import Path

from packrecorder.retention import purge_old_day_folders


def test_purge_only_dated_folders_older_than_keep(tmp_path: Path):
    root = tmp_path
    old = root / "2026-03-01"
    old.mkdir()
    recent = root / "2026-04-01"
    recent.mkdir()
    junk = root / "not-a-date"
    junk.mkdir()
    today = date(2026, 4, 6)
    removed = purge_old_day_folders(root, keep_days=16, today=today)
    assert old not in root.iterdir() or old not in list(root.iterdir())
    assert recent.exists()
    assert junk.exists()
```

- [ ] **Step 2: FAIL** — `pytest tests/test_retention.py -v`

- [ ] **Step 3: Implement**

```python
# src/packrecorder/retention.py
from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path

_DAY_DIR = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def purge_old_day_folders(root: Path, keep_days: int, today: date) -> list[Path]:
    if keep_days < 0:
        raise ValueError("keep_days must be >= 0")
    cutoff = today - timedelta(days=keep_days)
    removed: list[Path] = []
    if not root.is_dir():
        return removed
    for child in list(root.iterdir()):
        if not child.is_dir():
            continue
        if not _DAY_DIR.match(child.name):
            continue
        try:
            folder_date = date.fromisoformat(child.name)
        except ValueError:
            continue
        if folder_date < cutoff:
            import shutil
            shutil.rmtree(child, ignore_errors=True)
            removed.append(child)
    return removed
```

- [ ] **Step 4: Fix test assertion** (use explicit check)

Replace test body `removed` check:

```python
def test_purge_only_dated_folders_older_than_keep(tmp_path: Path):
    root = tmp_path
    old = root / "2026-03-01"
    old.mkdir()
    recent = root / "2026-04-01"
    recent.mkdir()
    junk = root / "not-a-date"
    junk.mkdir()
    today = date(2026, 4, 6)
    removed = purge_old_day_folders(root, keep_days=16, today=today)
    assert not old.exists()
    assert recent.exists()
    assert junk.exists()
    assert any("2026-03-01" in str(p) for p in removed) or not old.exists()
```

- [ ] **Step 5: PASS** — `pytest tests/test_retention.py -v`

- [ ] **Step 6: Commit**

```bash
git add src/packrecorder/retention.py tests/test_retention.py
git commit -m "feat(retention): purge yyyy-mm-dd folders older than keep_days"
```

---

### Task 5: order state machine (pure)

**Files:**
- Create: `src/packrecorder/order_state.py`
- Create: `tests/test_order_state.py`

- [ ] **Step 1: Tests**

```python
# tests/test_order_state.py
from packrecorder.order_state import OrderStateMachine, RecordingState


def test_idle_scan_starts_and_needs_duplicate_check():
    sm = OrderStateMachine()
    r = sm.on_scan("A", is_shutdown_countdown=False)
    assert r.new_active_order == "A"
    assert r.should_start_recording is True
    assert r.should_check_duplicate is True
    assert r.sound_event == "start_short"


def test_recording_same_order_stops():
    sm = OrderStateMachine()
    sm.on_scan("A", is_shutdown_countdown=False)
    sm.confirm_start_recording_succeeded()
    r = sm.on_scan("A", is_shutdown_countdown=False)
    assert r.should_stop_recording is True
    assert r.sound_event == "stop_double"


def test_switch_order_stop_then_start_b():
    sm = OrderStateMachine()
    sm.on_scan("A", is_shutdown_countdown=False)
    sm.confirm_start_recording_succeeded()
    r = sm.on_scan("B", is_shutdown_countdown=False)
    assert r.should_stop_recording is True
    assert r.pending_start_after_stop == "B"
    assert r.sound_event is None


def test_after_stop_confirm_start_b():
    sm = OrderStateMachine()
    sm.on_scan("A", is_shutdown_countdown=False)
    sm.confirm_start_recording_succeeded()
    sm.on_scan("B", is_shutdown_countdown=False)
    sm.confirm_stop_recording_succeeded()
    r = sm.confirm_start_recording_succeeded()
    assert r.should_check_duplicate is True
    assert r.sound_event == "start_short"


def test_shutdown_countdown_consumes_scan():
    sm = OrderStateMachine()
    r = sm.on_scan("X", is_shutdown_countdown=True)
    assert r.consume_for_shutdown_cancel is True
    assert r.should_start_recording is False
```

- [ ] **Step 2: FAIL** — `pytest tests/test_order_state.py -v`

- [ ] **Step 3: Implementation**

```python
# src/packrecorder/order_state.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

SoundEvent = Literal["start_short", "stop_double", "start_long", None]


@dataclass
class ScanResult:
    should_start_recording: bool = False
    should_stop_recording: bool = False
    should_check_duplicate: bool = False
    new_active_order: Optional[str] = None
    pending_start_after_stop: Optional[str] = None
    consume_for_shutdown_cancel: bool = False
    sound_event: SoundEvent = None


class RecordingState:
    IDLE = "idle"
    RECORDING = "recording"
    PENDING_START = "pending_start"


class OrderStateMachine:
    def __init__(self) -> None:
        self._phase = RecordingState.IDLE
        self._active_order: Optional[str] = None
        self._pending_order: Optional[str] = None

    def on_scan(self, code: str, *, is_shutdown_countdown: bool) -> ScanResult:
        code = code.strip()
        if is_shutdown_countdown:
            return ScanResult(consume_for_shutdown_cancel=True)
        if self._phase == RecordingState.PENDING_START:
            return ScanResult()
        if self._phase == RecordingState.IDLE:
            self._active_order = code
            self._phase = RecordingState.RECORDING
            return ScanResult(
                should_start_recording=True,
                should_check_duplicate=True,
                new_active_order=code,
                sound_event="start_short",
            )
        assert self._active_order is not None
        if code == self._active_order:
            return ScanResult(should_stop_recording=True, sound_event="stop_double")
        self._pending_order = code
        return ScanResult(should_stop_recording=True, pending_start_after_stop=code)

    def confirm_stop_recording_succeeded(self) -> ScanResult:
        if self._pending_order is not None:
            self._active_order = self._pending_order
            self._pending_order = None
            self._phase = RecordingState.RECORDING
            return ScanResult(
                should_start_recording=True,
                should_check_duplicate=True,
                new_active_order=self._active_order,
            )
        self._active_order = None
        self._phase = RecordingState.IDLE
        return ScanResult()

    def confirm_start_recording_succeeded(self, *, duplicate: bool = False) -> ScanResult:
        if duplicate:
            return ScanResult(sound_event="start_long")
        return ScanResult(sound_event="start_short")

    def apply_sound_after_start(self, duplicate: bool) -> ScanResult:
        return ScanResult(sound_event="start_long" if duplicate else "start_short")
```

- [ ] **Step 4: Adjust tests** — the state machine for switch B needs two-step sound: first `stop_double` on stop confirm, then `start_short`/`start_long` on start. Simpler API:

Refactor tests to match refined API below.

- [ ] **Step 3b: Replace `order_state.py` with coherent version**

```python
# src/packrecorder/order_state.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Optional

SoundEvent = Literal["start_short", "stop_double", "start_long"]


@dataclass
class ScanResult:
    should_start_recording: bool = False
    should_stop_recording: bool = False
    should_check_duplicate: bool = False
    new_active_order: Optional[str] = None
    pending_switch_to: Optional[str] = None
    consume_for_shutdown_cancel: bool = False
    sound_immediate: Optional[SoundEvent] = None


class OrderStateMachine:
    IDLE = "idle"
    RECORDING = "recording"

    def __init__(self) -> None:
        self._mode = self.IDLE
        self._order: Optional[str] = None
        self._switch_target: Optional[str] = None

    def on_scan(self, code: str, *, is_shutdown_countdown: bool) -> ScanResult:
        code = code.strip()
        if is_shutdown_countdown:
            return ScanResult(consume_for_shutdown_cancel=True)
        if self._mode == self.IDLE:
            self._order = code
            self._mode = self.RECORDING
            return ScanResult(
                should_start_recording=True,
                should_check_duplicate=True,
                new_active_order=code,
            )
        assert self._order is not None
        if code == self._order:
            return ScanResult(should_stop_recording=True, sound_immediate="stop_double")
        self._switch_target = code
        return ScanResult(should_stop_recording=True)

    def notify_stop_confirmed(self) -> ScanResult:
        if self._switch_target:
            tgt = self._switch_target
            self._switch_target = None
            self._order = tgt
            return ScanResult(
                should_start_recording=True,
                should_check_duplicate=True,
                new_active_order=tgt,
                sound_immediate="stop_double",
            )
        self._order = None
        self._mode = self.IDLE
        return ScanResult()

    @staticmethod
    def sound_for_start(*, duplicate: bool) -> SoundEvent:
        return "start_long" if duplicate else "start_short"
```

- [ ] **Step 3c: Replace tests**

```python
# tests/test_order_state.py
from packrecorder.order_state import OrderStateMachine


def test_idle_to_recording():
    sm = OrderStateMachine()
    r = sm.on_scan("A", is_shutdown_countdown=False)
    assert r.should_start_recording and r.should_check_duplicate
    assert r.new_active_order == "A"
    assert r.sound_immediate is None


def test_stop_same_order_plays_double():
    sm = OrderStateMachine()
    sm.on_scan("A", is_shutdown_countdown=False)
    r = sm.on_scan("A", is_shutdown_countdown=False)
    assert r.should_stop_recording
    assert r.sound_immediate == "stop_double"


def test_switch_orders_sequence():
    sm = OrderStateMachine()
    sm.on_scan("A", is_shutdown_countdown=False)
    r1 = sm.on_scan("B", is_shutdown_countdown=False)
    assert r1.should_stop_recording and r1.sound_immediate is None
    r2 = sm.notify_stop_confirmed()
    assert r2.should_start_recording and r2.new_active_order == "B"
    assert r2.sound_immediate == "stop_double"


def test_shutdown_countdown():
    sm = OrderStateMachine()
    assert sm.on_scan("X", is_shutdown_countdown=True).consume_for_shutdown_cancel is True
```

- [ ] **Step 4: PASS** — `pytest tests/test_order_state.py -v`

- [ ] **Step 5: Commit**

```bash
git add src/packrecorder/order_state.py tests/test_order_state.py
git commit -m "feat(order_state): scan-driven record transitions"
```

---

### Task 6: shutdown scheduler

**Files:**
- Create: `src/packrecorder/shutdown_scheduler.py`
- Create: `tests/test_shutdown_scheduler.py`

- [ ] **Step 1: Tests (fixed timezone naive local)**

```python
# tests/test_shutdown_scheduler.py
from datetime import date, datetime, time, timedelta

from packrecorder.shutdown_scheduler import compute_next_shutdown_at, defer_one_hour


def test_next_shutdown_today_if_not_passed():
    cfg = time(18, 0)
    now = datetime(2026, 4, 6, 10, 0, 0)
    n = compute_next_shutdown_at(cfg, now)
    assert n == datetime(2026, 4, 6, 18, 0, 0)


def test_next_shutdown_tomorrow_if_passed():
    cfg = time(18, 0)
    now = datetime(2026, 4, 6, 19, 0, 0)
    n = compute_next_shutdown_at(cfg, now)
    assert n.date() == date(2026, 4, 7)


def test_defer_one_hour():
    base = datetime(2026, 4, 6, 18, 0, 0)
    assert defer_one_hour(base) == base + timedelta(hours=1)
```

- [ ] **Step 2: Implement**

```python
# src/packrecorder/shutdown_scheduler.py
from __future__ import annotations

from datetime import datetime, time, timedelta


def compute_next_shutdown_at(config_time: time, now: datetime) -> datetime:
    candidate = now.replace(
        hour=config_time.hour,
        minute=config_time.minute,
        second=0,
        microsecond=0,
    )
    if candidate <= now:
        candidate = candidate + timedelta(days=1)
    return candidate


def defer_one_hour(now: datetime) -> datetime:
    return now + timedelta(hours=1)
```

- [ ] **Step 3: PASS** — `pytest tests/test_shutdown_scheduler.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/packrecorder/shutdown_scheduler.py tests/test_shutdown_scheduler.py
git commit -m "feat(scheduler): next shutdown and defer +1h"
```

---

### Task 7: Windows Job Object for child PID

**Files:**
- Create: `src/packrecorder/windows_job.py`

- [ ] **Step 1: Implement (no pytest on CI without Windows — manual verify)**

```python
# src/packrecorder/windows_job.py
from __future__ import annotations

import ctypes
from ctypes import wintypes


def assign_process_to_job_object(pid: int) -> None:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise OSError(ctypes.get_last_error())
    info = JOBOBJECT_EXTENDED_LIMIT_INFORMATION()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    infolen = ctypes.sizeof(JOBOBJECT_EXTENDED_LIMIT_INFORMATION)
    if not kernel32.SetInformationJobObject(
        job,
        9,  # JobObjectExtendedLimitInformation
        ctypes.byref(info),
        infolen,
    ):
        raise OSError(ctypes.get_last_error())
    h_process = kernel32.OpenProcess(0x001F0FFF, False, pid)
    if not h_process:
        raise OSError(ctypes.get_last_error())
    if not kernel32.AssignProcessToJobObject(job, h_process):
        raise OSError(ctypes.get_last_error())
    kernel32.CloseHandle(h_process)
    # job handle intentionally leaked for process lifetime; close on app exit OS reaps


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", wintypes.ULARGE_INTEGER),
        ("WriteOperationCount", wintypes.ULARGE_INTEGER),
        ("OtherOperationCount", wintypes.ULARGE_INTEGER),
        ("ReadTransferCount", wintypes.ULARGE_INTEGER),
        ("WriteTransferCount", wintypes.ULARGE_INTEGER),
        ("OtherTransferCount", wintypes.ULARGE_INTEGER),
    ]


class JOBOBJECT_BASIC_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", wintypes.LARGE_INTEGER),
        ("PerJobUserTimeLimit", wintypes.LARGE_INTEGER),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_ulong_ptr),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class JOBOBJECT_EXTENDED_LIMIT_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", JOBOBJECT_BASIC_LIMIT_INFORMATION),
        ("IoInfo", IO_COUNTERS),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]
```

- [ ] **Step 2: Manual test on Windows**

Run a one-liner in `python -c` spawning `ping` and attach — confirm parent kill kills child (document in README).

- [ ] **Step 3: Commit**

```bash
git add src/packrecorder/windows_job.py
git commit -m "feat(win32): job object kill-on-close for child process"
```

---

### Task 8: FFmpeg raw pipe recorder (unit-test with mock Popen)

**Files:**
- Create: `src/packrecorder/ffmpeg_pipe_recorder.py`
- Create: `tests/test_ffmpeg_pipe_recorder.py`

- [ ] **Step 1: Test mock**

```python
# tests/test_ffmpeg_pipe_recorder.py
from pathlib import Path
from unittest.mock import MagicMock, patch

from packrecorder.ffmpeg_pipe_recorder import FFmpegPipeRecorder


@patch("packrecorder.ffmpeg_pipe_recorder.subprocess.Popen")
def test_start_builds_command_and_writes_header(mock_popen, tmp_path: Path):
    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.poll.return_value = None
    mock_popen.return_value = proc
    out = tmp_path / "o.mp4"
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_text("fake")
    rec = FFmpegPipeRecorder(ffmpeg_exe=ffmpeg, width=320, height=240, fps=15)
    rec.start(out)
    args, kwargs = mock_popen.call_args
    cmd = args[0]
    assert "-f" in cmd and "rawvideo" in cmd
    assert str(out) in cmd
    rec.stop()
    proc.stdin.close.assert_called()
    proc.wait.assert_called()
```

- [ ] **Step 2: Implement minimal class**

```python
# src/packrecorder/ffmpeg_pipe_recorder.py
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Optional

from packrecorder.windows_job import assign_process_to_job_object


class FFmpegPipeRecorder:
    def __init__(
        self,
        ffmpeg_exe: Path,
        width: int,
        height: int,
        fps: int,
        *,
        attach_job: bool = True,
    ) -> None:
        self._ffmpeg = ffmpeg_exe
        self._w, self._h, self._fps = width, height, fps
        self._attach_job = attach_job
        self._proc: Optional[subprocess.Popen] = None

    def start(self, output_mp4: Path) -> None:
        output_mp4.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            str(self._ffmpeg),
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{self._w}x{self._h}",
            "-r",
            str(self._fps),
            "-i",
            "-",
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            str(output_mp4),
        ]
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if self._attach_job and self._proc.pid:
            assign_process_to_job_object(self._proc.pid)

    def write_frame(self, bgr_bytes: bytes) -> None:
        if self._proc and self._proc.stdin:
            self._proc.stdin.write(bgr_bytes)

    def stop(self, timeout: float = 15.0) -> None:
        if not self._proc:
            return
        if self._proc.stdin:
            self._proc.stdin.close()
        self._proc.wait(timeout=timeout)
        self._proc = None
```

- [ ] **Step 3: On real Windows test**, run app recording 2s — verify playable MP4.

- [ ] **Step 4: Commit**

```bash
git add src/packrecorder/ffmpeg_pipe_recorder.py tests/test_ffmpeg_pipe_recorder.py
git commit -m "feat(record): ffmpeg raw bgr24 pipe with job attach"
```

---

### Task 9: config persistence

**Files:**
- Create: `src/packrecorder/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Test roundtrip**

```python
# tests/test_config.py
import json
from pathlib import Path

from packrecorder.config import AppConfig, load_config, save_config


def test_save_load(tmp_path: Path):
    p = tmp_path / "c.json"
    c = AppConfig(
        video_root=str(tmp_path / "v"),
        camera_index=0,
        packer_label="Máy 2",
    )
    save_config(p, c)
    c2 = load_config(p)
    assert c2.video_root == c.video_root
    assert c2.camera_index == 0
    assert c2.packer_label == "Máy 2"
```

- [ ] **Step 2: Implement `AppConfig` as dataclass** with fields: `video_root`, `camera_index`, **`packer_label: str = "Máy 1"`**, `shutdown_enabled`, `shutdown_time_hhmm` (default `"18:00"`), `sound_enabled`, `sound_mode` (`speaker`/`scanner_host`), `beep_short_ms`, `beep_gap_ms`, `beep_long_ms`, paths to optional WAVs.

Use `dataclasses.asdict` + `json.dump`.

- [ ] **Step 3: PASS** — `pytest tests/test_config.py -v`

- [ ] **Step 4: Commit**

```bash
git add src/packrecorder/config.py tests/test_config.py
git commit -m "feat(config): json persistence for app settings"
```

---

### Task 10: Scan worker + debounce

**Files:**
- Create: `src/packrecorder/scan_worker.py`

- [ ] **Step 1: Implement** `ScanWorker(QThread)` with `time.monotonic()` debounce 350ms, `pyzbar.decode`, emit `decoded.emit(str)` only when code changes or debounce window passed.

- [ ] **Step 2: Manual test** with webcam printed QR.

- [ ] **Step 3: Commit**

```bash
git add src/packrecorder/scan_worker.py
git commit -m "feat(scan): opencv capture thread with pyzbar debounce"
```

---

### Task 11: Feedback sound player

**Files:**
- Create: `src/packrecorder/feedback_sound.py`

- [ ] **Step 1: Implement** `FeedbackPlayer` with methods `play_short`, `play_double`, `play_long` using `QSoundEffect` and `QTimer.singleShot` for gap; load from `resources/sounds/` or config paths.

- [ ] **Step 2: Commit**

```bash
git add src/packrecorder/feedback_sound.py resources/sounds/README.txt
git commit -m "feat(audio): speaker beep patterns per spec 3.6"
```

---

### Task 12: UI — MainWindow integration

**Files:**
- Create: `src/packrecorder/ui/main_window.py`
- Create: `src/packrecorder/ui/styles.qss`
- Modify: `src/packrecorder/app.py`
- Modify: `src/packrecorder/__main__.py`

- [ ] **Step 1: `app.py`**

```python
# src/packrecorder/app.py
import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from packrecorder.ui.main_window import MainWindow


def run_app() -> int:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    qss = Path(__file__).resolve().parent / "ui" / "styles.qss"
    if qss.is_file():
        app.setStyleSheet(qss.read_text(encoding="utf-8"))
    w = MainWindow()
    w.show()
    return app.exec()
```

- [ ] **Step 2: `__main__.py`**

```python
from packrecorder.app import run_app

def main() -> None:
    raise SystemExit(run_app())
```

- [ ] **Step 3: `MainWindow`** wires: load config, `QTimer` 45s for `purge_old_day_folders` + `compute_next_shutdown_at` refresh on startup, `ScanWorker`, `OrderStateMachine`, on start recording resolve duplicate with `is_duplicate_order`, show `QStatusBar` message 5s, call `FeedbackPlayer.sound_for_start`, **`build_output_path(root, order, config.packer_label, datetime.now())`**, spawn `FFmpegPipeRecorder` with frame size from `cap.get(cv2.CAP_PROP_FRAME_WIDTH/HEIGHT)`, in timer read frame write `write_frame`, on stop `recorder.stop()`, play sounds per `sound_immediate`; **status bar** có thể hiển thị nhãn **Máy 1**/**Máy 2** đang chọn.

- [ ] **Step 4: Run** — `python -m packrecorder` (from `src` on PYTHONPATH or pip -e).

- [ ] **Step 5: Commit**

```bash
git add src/packrecorder/app.py src/packrecorder/__main__.py src/packrecorder/ui/
git commit -m "feat(ui): main window integrate scan and record"
```

---

### Task 13: Countdown shutdown dialog

**Files:**
- Create: `src/packrecorder/ui/countdown_dialog.py`
- Modify: `src/packrecorder/ui/main_window.py`

- [ ] **Step 1: Implement** modal `QDialog` with `QLCDNumber` or label, `QTimer` 1s, property `is_shutdown_mode` on main controller so scans cancel and emit to dialog; on accept cancel `defer_one_hour`.

- [ ] **Step 2: On timeout 0** call `subprocess.run(["shutdown", "/s", "/t", "0"], check=False)` after internal `shutdown()` releases resources.

- [ ] **Step 3: Commit**

```bash
git add src/packrecorder/ui/countdown_dialog.py src/packrecorder/ui/main_window.py
git commit -m "feat(shutdown): 60s scan-cancel and windows shutdown"
```

---

### Task 14: Settings dialog + QSettings path

**Files:**
- Create: `src/packrecorder/ui/settings_dialog.py`

- [ ] **Step 1: Fields** per `AppConfig` — **`QComboBox` editable** với `addItems(["Máy 1", "Máy 2"])` làm preset; lưu `currentText()` vào `packer_label`; on save re-init `next_shutdown_at`.

- [ ] **Step 2: Commit**

```bash
git add src/packrecorder/ui/settings_dialog.py
git commit -m "feat(settings): configure root path camera and shutdown"
```

---

### Task 15: PyInstaller + FFmpeg bundle

**Files:**
- Create: `packrecorder.spec` (PyInstaller)
- Create: `README.md` (operator: install ZBar DLL, place ffmpeg.exe)

- [ ] **Step 1: Command**

```bash
pyinstaller --onefile --windowed --name PackRecorder ^
  --add-binary "path\to\ffmpeg.exe;." ^
  --collect-all PySide6 ^
  src/packrecorder/__main__.py
```

Adjust paths for Windows; document `pyzbar` needs `libzbar-64.dll` in same folder or PATH.

- [ ] **Step 2: Commit**

```bash
git add packrecorder.spec README.md
git commit -m "build: pyinstaller spec and operator readme"
```

---

## Self-review (plan author)

**1. Spec coverage**

| Spec section | Task(s) |
|--------------|---------|
| §1 MVP one camera, no audio in MP4 | Task 8 `-an`, OpenCV single capture |
| §3.2 state table | Task 5 + 12 |
| §3.3 debounce | Task 10 |
| §3.4 shutdown scan priority | Task 12 flag `is_shutdown_countdown` + 13 |
| §3.5 duplicate + long beep only | Task 3, 12, 11 |
| §3.6 beep patterns | Task 11; `ScannerHostBeep` stub in Task 11 file |
| §4 paths / retention / **packer trong tên file** | Task 2 (`sanitize_packer_label`), 3 (glob `maDon_` vẫn khớp), 9, 12, 14 |
| §8 shutdown flow | Task 6, 13 |
| §9 Job Object, shutdown cleanup | Task 7, 8, 13, 12 `atexit` hook |
| §12 Phase 2 PIP | Out of scope — separate plan |

**2. Placeholder scan:** No `TBD` in executable steps; WAV files documented via README; scanner host beep explicitly `NullScannerHostBeep` until model known.

**3. Type consistency:** `OrderStateMachine.notify_stop_confirmed` returns `ScanResult` with `sound_immediate="stop_double"` on switch — UI must play **two short** after stop, then on successful FFmpeg start call `FeedbackPlayer.play(OrderStateMachine.sound_for_start(duplicate=...))` for second tone. Adjust Task 12 narrative: after `notify_stop_confirmed`, UI plays `stop_double` once; after new FFmpeg `start` succeeds, play `start_short` or `start_long`. Task 5 code currently sets `sound_immediate` on `notify_stop_confirmed` to `"stop_double"` which duplicates semantic — **fix in implementation:** remove `sound_immediate` from `notify_stop_confirmed` and let UI play `stop_double` when `should_stop_recording` was True and stop completed; then play start sound. **Implementation fix:** merge Task 5 follow-up commit adjusting `notify_stop_confirmed` to not emit `stop_double` (already played on stop success path). Plan execution: add **Task 5b** one commit to set `sound_immediate` only on `on_scan` when `should_stop_recording`.

---

### Task 5b: Fix sound flags (follow-up)

**Files:**
- Modify: `src/packrecorder/order_state.py`
- Modify: `tests/test_order_state.py`

- [ ] **Step 1: `notify_stop_confirmed` returns no sound; UI plays `stop_double` when user-initiated stop finished.**

```python
# In notify_stop_confirmed — remove sound_immediate stop_double
def notify_stop_confirmed(self) -> ScanResult:
    if self._switch_target:
        tgt = self._switch_target
        self._switch_target = None
        self._order = tgt
        return ScanResult(
            should_start_recording=True,
            should_check_duplicate=True,
            new_active_order=tgt,
        )
    self._order = None
    self._mode = self.IDLE
    return ScanResult()
```

- [ ] **Step 2: Update test_switch_orders_sequence** — remove assert on `sound_immediate == "stop_double"` from `notify_stop_confirmed`.

- [ ] **Step 3: Commit** — `git commit -m "fix(order_state): defer stop_double to UI on stop complete"`

---

Plan complete and saved to `docs/superpowers/plans/2026-04-06-pack-video-recorder-mvp.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** — dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — execute tasks in this session using executing-plans, batch execution with checkpoints.

**Which approach do you want?**
