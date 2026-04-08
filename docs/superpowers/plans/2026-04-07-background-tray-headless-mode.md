# Pack Recorder — chế độ chạy nền (Tray + không cửa sổ phụ + ưu tiên CPU) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cho phép Pack Recorder “biến mất” khỏi taskbar chính (vào system tray), tiếp tục quay/đồng bộ/ghi log khi cửa sổ bị ẩn; tránh cửa sổ console FFmpeg; tùy chọn hạ độ ưu tiên CPU; tùy chọn thông báo/health; **không** phá luồng quét mã hiện tại trừ khi bật rõ ràng tính năng rủi ro (global hook).

**Architecture:** Tầng UI dùng `QSystemTrayIcon` (PySide6 có sẵn, không cần `pystray`). Đóng cửa sổ (X) = `hide()` + giữ `QApplication` chạy khi cấu hình `minimize_to_tray`; menu tray “Thoát” mới gọi đường dọn dẹp hiện có trong `MainWindow.closeEvent`. Tầng process: helper Windows `subprocess_popen_kwargs()` thêm `CREATE_NO_WINDOW` cho mọi `Popen`/`run` liên quan FFmpeg. Tầng OpenCV: repo **không** dùng `cv2.imshow`; preview là widget Qt — chế độ “headless UI” nghĩa là ẩn cửa sổ chính / **giảm hoặc tạm dừng cập nhật preview** (xem Lưu ý bổ sung mục 2), không phải xóa `imshow`. Tầng input: máy quét dạng bàn phím (wedge) thường cần focus ô nhập; global hotkey (`pynput`) là **tùy chọn**, tắt mặc định, có cảnh báo xung đột với Qt; ưu tiên **COM Serial** khi triển khai thực tế (Lưu ý bổ sung mục 1).

**Tech Stack:** Python 3.11+, PySide6, OpenCV (capture trong worker/pipeline), FFmpeg qua `FFmpegPipeRecorder`, tùy chọn `psutil` cho priority, tùy chọn `pynput` chỉ khi bật global listener.

---

## File map (tạo / sửa)

| File | Vai trò |
|------|---------|
| `src/packrecorder/config.py` | Thêm field cấu hình: `minimize_to_tray`, `start_in_tray`, `low_process_priority`, `tray_show_toast_on_order`, `tray_health_beep_interval_min` (0=tắt), `tray_health_beep_volume` (0.0–1.0, xem Lưu ý bổ sung mục 3), `enable_global_barcode_hook` (mặc định False). Bump `schema_version` + migrate trong `normalize_config`. |
| `src/packrecorder/subprocess_win.py` (mới) | `def popen_creationflags() -> int` và `def subprocess_run_kwargs() -> dict` gom `CREATE_NO_WINDOW` trên win32. |
| `src/packrecorder/ffmpeg_pipe_recorder.py` | `Popen(..., **subprocess_run_kwargs())` hoặc truyền `creationflags`. |
| `src/packrecorder/ffmpeg_encoders.py` | `subprocess.run(..., **subprocess_run_kwargs())` để không nháy console khi probe encoder. |
| `src/packrecorder/app.py` | `app.setQuitOnLastWindowClosed(False)` khi bật tray (hoặc luôn False nếu tray luôn bật). Khởi tạo tray cùng `MainWindow` hoặc delegate `MainWindow` tạo tray. |
| `src/packrecorder/ui/main_window.py` | `QSystemTrayIcon`, menu (Show / Settings / Quit), `closeEvent` nhánh hide-vs-quit, đồng bộ icon trạng thái (OK / lỗi camera nếu đã có signal). |
| `src/packrecorder/ui/settings_dialog.py` | Checkbox các tùy chọn mới. |
| `pyproject.toml` | Optional deps: `psutil`, `pynput` (nhóm ví dụ `[project.optional-dependencies] background = [...]`). |
| `tests/test_config.py` | Serialize/defaults cho field mới. |
| `tests/test_subprocess_win.py` (mới) | Trên Windows assert `creationflags` có bit; trên Linux assert kwargs rỗng. |

---

### Task 1: Helper Windows cho subprocess (CREATE_NO_WINDOW)

**Files:**
- Create: `src/packrecorder/subprocess_win.py`
- Modify: `src/packrecorder/ffmpeg_pipe_recorder.py`, `src/packrecorder/ffmpeg_encoders.py`
- Test: `tests/test_subprocess_win.py`

- [ ] **Step 1: Viết helper**

```python
# src/packrecorder/subprocess_win.py
from __future__ import annotations

import subprocess
import sys
from typing import Any


def popen_extra_kwargs() -> dict[str, Any]:
    """Windows: tránh cửa sổ console khi spawn ffmpeg/tools."""
    if sys.platform != "win32":
        return {}
    cf = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if not cf:
        return {}
    return {"creationflags": cf}


def run_extra_kwargs() -> dict[str, Any]:
    return popen_extra_kwargs()
```

- [ ] **Step 2: Gắn vào FFmpegPipeRecorder.start()**

Trong `ffmpeg_pipe_recorder.py`, import `popen_extra_kwargs` và spread vào `subprocess.Popen`:

```python
self._proc = subprocess.Popen(
    cmd,
    stdin=subprocess.PIPE,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    **popen_extra_kwargs(),
)
```

- [ ] **Step 3: Gắn vào ffmpeg_encoders `subprocess.run`**

```python
r = subprocess.run(
    [str(ffmpeg_exe), "-hide_banner", "-encoders"],
    capture_output=True,
    timeout=20,
    text=True,
    encoding="utf-8",
    errors="replace",
    **run_extra_kwargs(),
)
```

- [ ] **Step 4: Test**

```python
# tests/test_subprocess_win.py
import sys
from packrecorder.subprocess_win import popen_extra_kwargs, run_extra_kwargs


def test_extra_kwargs_platform_specific():
    d = popen_extra_kwargs()
    if sys.platform == "win32":
        assert "creationflags" in d
    else:
        assert d == {}
    assert isinstance(run_extra_kwargs(), dict)
```

Chạy: `pytest tests/test_subprocess_win.py -v` — Expected: PASS trên mọi OS.

- [ ] **Step 5: Commit**

```bash
git add src/packrecorder/subprocess_win.py src/packrecorder/ffmpeg_pipe_recorder.py src/packrecorder/ffmpeg_encoders.py tests/test_subprocess_win.py
git commit -m "fix(win): hide FFmpeg subprocess console windows"
```

---

### Task 2: Cấu hình + migrate cho chế độ tray

**Files:**
- Modify: `src/packrecorder/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Thêm field vào `AppConfig`**

```python
# Trong AppConfig (gần window_always_on_top)
minimize_to_tray: bool = False
start_in_tray: bool = False
close_to_tray: bool = True  # khi minimize_to_tray True: nút X = ẩn, không thoát
low_process_priority: bool = False
tray_show_toast_on_order: bool = True
tray_health_beep_interval_min: int = 0  # 0 = tắt; ví dụ 10 = mỗi 10 phút
enable_global_barcode_hook: bool = False
```

Bump `schema_version` (ví dụ 6 → 7) và trong `normalize_config` gán mặc định cho key thiếu (theo pattern file hiện có).

- [ ] **Step 2: Test round-trip JSON**

Mở rộng test có sẵn trong `tests/test_config.py`: load default → `normalize_config` → assert các key mới tồn tại và kiểu đúng.

Chạy: `pytest tests/test_config.py -v` — Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add src/packrecorder/config.py tests/test_config.py
git commit -m "feat(config): tray and background behavior flags"
```

---

### Task 3: QSystemTrayIcon + đóng cửa sổ = ẩn (không quit)

**Files:**
- Modify: `src/packrecorder/app.py`, `src/packrecorder/ui/main_window.py`
- Test: `tests/test_main_window_tray.py` (pytest-qt) hoặc unit test thuần mock `QSystemTrayIcon` nếu headless CI không có tray

- [ ] **Step 1: `setQuitOnLastWindowClosed`**

Trong `run_app()`, sau `QApplication(sys.argv)`:

```python
app.setQuitOnLastWindowClosed(False)
```

(Giữ False khi tray bật; nếu sợ đổi hành vi khi tray tắt, có thể `app.setQuitOnLastWindowClosed(not config.minimize_to_tray)` sau khi load config — cần load config sớm hoặc đọc một lần từ `default_config_path()`.)

- [ ] **Step 2: MainWindow — tạo tray**

Trong `MainWindow.__init__` (sau khi có `self._config`):

```python
from PySide6.QtWidgets import QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon
# self._tray: QSystemTrayIcon | None
self._tray = QSystemTrayIcon(self)
self._tray.setToolTip("Pack Recorder")
# icon: dùng windowIcon() hoặc resource có sẵn; nếu chưa có file .ico, set từ theme hoặc pixmap 16x16 tạm
menu = QMenu()
act_show = menu.addAction("Hiện cửa sổ")
act_show.triggered.connect(self._show_from_tray)
menu.addSeparator()
act_quit = menu.addAction("Thoát")
act_quit.triggered.connect(QApplication.instance().quit)
self._tray.setContextMenu(menu)
self._tray.activated.connect(self._on_tray_activated)
```

Implement `_on_tray_activated` để double-click mở lại cửa sổ.

`self._tray.show()` khi `self._config.minimize_to_tray` True (hoặc luôn show icon khi feature được bật trong settings).

- [ ] **Step 3: `closeEvent` — nhánh hide**

Đầu `closeEvent`, nếu `self._config.minimize_to_tray` và `self._config.close_to_tray`:

```python
if self._config.minimize_to_tray and self._config.close_to_tray:
    event.ignore()
    self.hide()
    if self._tray:
        self._tray.showMessage(
            "Pack Recorder",
            "Ứng dụng vẫn chạy nền. Mở lại từ biểu tượng khay hệ thống.",
            QSystemTrayIcon.MessageIcon.Information,
            3000,
        )
    return
```

Giữ nguyên nhánh hiện tại (sync worker stop, cleanup) **chỉ** khi thoát thật (menu Thoát hoặc `close_to_tray` False).

- [ ] **Step 4: Thoát thật từ menu**

`act_quit` phải gọi một slot `self._quit_application()` gọi `self._cleanup_workers()` tương đương `closeEvent` hiện tại rồi `QApplication.quit()`.

- [ ] **Step 5: Test thủ công**

Mở app, bật minimize_to_tray trong settings, bấm X → cửa sổ biến, icon tray còn, quá trình ghi/sync vẫn chạy (quan sát file video / log).

- [ ] **Step 6: Commit**

```bash
git add src/packrecorder/app.py src/packrecorder/ui/main_window.py
git commit -m "feat(ui): system tray and close-to-background"
```

---

### Task 4: Toast khi có đơn / đổi màu icon trạng thái

**Files:**
- Modify: `src/packrecorder/ui/main_window.py` (hook vào chỗ đã xử lý mã đơn / bắt đầu ghi)

- [ ] **Step 1: Khi `tray_show_toast_on_order` và có `_tray`**

Tại điểm đã biết order id (ví dụ sau khi state machine chấp nhận quét), gọi:

```python
if self._config.tray_show_toast_on_order and self._tray and not self.isVisible():
    self._tray.showMessage(
        "Pack Recorder",
        f"Đang quay đơn: {order_id[:40]}",
        QSystemTrayIcon.MessageIcon.Information,
        2000,
    )
```

- [ ] **Step 2: Icon đỏ/xanh**

Tạo hai `QIcon` (pixmap 16x16 xanh lá / đỏ) hoặc đổi `QSystemTrayIcon` qua `setIcon` khi `capture_failed` vs healthy — nối với signal/worker đã có (`_on_worker_capture_failed`).

- [ ] **Step 3: Commit**

```bash
git add src/packrecorder/ui/main_window.py
git commit -m "feat(ui): tray toasts and status icon colors"
```

---

### Task 5: Độ ưu tiên tiến trình (Below Normal)

**Files:**
- Modify: `pyproject.toml` (optional `psutil`)
- Modify: `src/packrecorder/app.py` hoặc `main_window.py` — gọi một lần khi `low_process_priority` True

- [ ] **Step 1: Hàm tiện ích**

```python
# src/packrecorder/process_priority.py
from __future__ import annotations

import os
import sys


def set_current_process_below_normal() -> bool:
    if sys.platform != "win32":
        try:
            os.nice(5)
            return True
        except Exception:
            return False
    try:
        import psutil
        p = psutil.Process(os.getpid())
        p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        return True
    except Exception:
        return False
```

- [ ] **Step 2: Gọi sau `QApplication` tạo**

Nếu `config.low_process_priority`: gọi `set_current_process_below_normal()`.

- [ ] **Step 3: Test smoke**

`pytest` không bắt buộc mock psutil; có thể test "import không lỗi khi không cài psutil" bằng try/except và log warning.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml src/packrecorder/process_priority.py src/packrecorder/app.py
git commit -m "feat: optional below-normal process priority (psutil on Windows)"
```

---

### Task 6: Global hotkey / listener (TÙY CHỌN, tắt mặc định)

**Files:**
- Create: `src/packrecorder/global_input_optional.py` (stub)
- Modify: `src/packrecorder/ui/main_window.py` — chỉ import khi `enable_global_barcode_hook`

**Cảnh báo sản phẩm:** `pynput` có thể xung đột với Qt; máy quét wedge thường gửi ký tự vào control đang focus — khi app ẩn, focus có thể là Zalo, Excel, trình duyệt, không phải Pack Recorder. Chi tiết và lời khuyên COM (Serial): xem **Lưu ý bổ sung (hoàn thiện sản phẩm) → mục 1**.

- [ ] **Step 1:** Nếu `enable_global_barcode_hook`, khởi động thread listener đọc buffer đến Enter, emit `Qt` signal sang main thread — **không** triển khai đầy đủ trong sprint đầu nếu chưa có test; có thể để `raise NotImplementedError` sau log + QMessageBox.

- [ ] **Step 2: Commit doc trong plan** — hoàn thiện ở sprint sau khi có thiết kế signal/order pipeline.

---

### Task 7: Logging & health beep (đã có session_log — mở rộng nhẹ)

**Files:**
- Modify: `src/packrecorder/ui/main_window.py` — `QTimer` mỗi `tray_health_beep_interval_min * 60 * 1000` ms nếu > 0 và cửa sổ ẩn: phát tiếng ngắn qua `FeedbackPlayer` nếu `sound_enabled`.

- [ ] **Step 1:** Tái sử dụng `FeedbackPlayer` / beep config hiện có; không thêm file log mới trừ khi thiếu — `session_log` / `run_errors.log` đã phục vụ "chạy ngầm". **Âm lượng / UX kho yên tĩnh:** xem **Lưu ý bổ sung → mục 3** (mặc định tắt hoặc rất nhẹ; thêm `tray_health_beep_volume` hoặc tương đương nếu có chỗ trong `AppConfig`).

- [ ] **Step 2: Commit**

```bash
git add src/packrecorder/ui/main_window.py
git commit -m "feat: optional tray health beep interval"
```

---

### Task 8: Settings UI + `start_in_tray`

**Files:**
- Modify: `src/packrecorder/ui/settings_dialog.py`, `main_window.py` (startup `hide()` nếu `start_in_tray`)

- [ ] **Step 1:** Checkbox bind field config; lưu qua `save_config`.

- [ ] **Step 2:** Sau `show()` trong `run_app`, nếu `start_in_tray` và `minimize_to_tray`: `w.hide()` và đảm bảo tray visible.

- [ ] **Step 3: Commit**

```bash
git add src/packrecorder/ui/settings_dialog.py src/packrecorder/ui/main_window.py
git commit -m "feat(settings): tray options and start minimized to tray"
```

---

## Lưu ý bổ sung (hoàn thiện sản phẩm)

Các điểm dưới đây không thay thế các task trên nhưng giúp triển khai và vận hành thực tế (kho, văn phòng yên tĩnh) khớp kỳ vọng người dùng.

### 1. Global hotkey / máy quét kiểu bàn phím (HID wedge)

Đây vẫn là **phần rủi ro cao nhất** trong kế hoạch. Khi app ẩn (`hide()`), nếu máy quét hoạt động như **thiết bị HID giả lập bàn phím**, chuỗi ký tự sẽ đi vào **bất kỳ ô nào đang có focus** trên hệ thống — ví dụ ô chat Zalo, ô tìm kiếm trình duyệt, ô trong Excel — chứ không “tự biết” phải gửi cho Pack Recorder.

**Lời khuyên sản phẩm:**

- Ưu tiên **tài liệu và UI** nhắc rõ: chế độ wedge + app ẩn dễ gây nhập nhầm chỗ; nên đưa cửa sổ lên hoặc dùng ô nhập tập trung khi làm việc quan trọng.
- **Chuẩn COM (Serial)** cho máy quét (đã có hướng trong codebase qua `scanner_serial_port` / `SerialScanWorker`) **không phụ thuộc focus** — nên nhấn mạnh trong hướng dẫn triển khai: nếu phần cứng hỗ trợ COM, cấu hình COM để quét ổn định khi chạy nền thay vì dựa vào wedge + global hook.
- `pynput` / listener toàn cục chỉ nên là **đường dự phòng**, tắt mặc định, kèm cảnh báo trong Settings.

### 2. Quản lý Preview khi cửa sổ ẩn

Khi `hide()`, luồng **hiển thị** lên widget (preview camera) vẫn có thể tiêu tốn GPU/CPU nếu timer/signal vẫn cập nhật 30 fps.

**Hướng xử lý khi implement Task 3 + luồng preview:**

- Khi `MainWindow` chuyển sang trạng thái ẩn (hoặc `isMinimized()` / không visible): **giảm tần suất** cập nhật preview xuống mức tối thiểu (ví dụ 1–2 fps hoặc tắt hẳn repaint preview), hoặc **ngắt** kết nối tạm thời giữa nguồn frame “chỉ để xem” và widget — **không** được dừng luồng **ghi file** và **decode/quét mã** trừ khi người dùng tắt tính năng đó.
- Tách rõ trong code: “preview path” vs “record + scan path” để tránh một cờ `hidden` làm lỡ cả pipeline ghi hình.

### 3. Health beep — âm lượng và môi trường làm việc

Tính năng “bíp định kỳ để xác nhận còn sống” rất hữu ích khi **không có** màn hình, nhưng trong **kho yên tĩnh** hoặc văn phòng chung, tiếng bíp chói tai mỗi 10 phút sẽ khiến nhân viên **tắt app** hoặc tắt loa.

**Đề xuất khi implement Task 7:**

- Mặc định: **âm cực nhẹ** (file WAV ngắn, biên độ thấp) hoặc **tắt** (interval = 0) và để người dùng bật có chủ đích.
- Thêm cấu hình (tối thiểu): **`tray_health_beep_volume`** (0.0–1.0) hoặc tái sử dụng/tách mức âm lượng riêng cho “health ping” so với tiếng quét thường; nếu stack âm thanh hiện tại không hỗ trợ volume per-channel, ghi ràng buộc trong plan và ưu tiên **tắt mặc định** + chỉ bật khi người dùng xác nhận.
- Cân nhắc **thay thế hoặc bổ sung** bằng: chỉ đổi icon tray (xanh/đỏ), toast nhẹ, hoặc log — không bắt buộc luôn dùng âm thanh.

---

## Kiểm tra cuối (self-review)

**1. Spec coverage**

| Yêu cầu trong spec | Task |
|---------------------|------|
| System tray, X không thoát | Task 3 |
| Không `cv2.imshow` (đã không có) | Ghi chú trong Task 1 — preview Qt vẫn có thể tắt bằng ẩn cửa sổ |
| FFmpeg không console | Task 1 |
| Priority thấp | Task 5 |
| Global hotkey | Task 6 (optional, rủi ro) |
| Toast | Task 4 |
| Log + icon/beep | Task 4 + 7 + session hiện có |
| Preview tiết kiệm CPU/GPU khi ẩn | Lưu ý bổ sung → mục 2 (kết hợp Task 3) |
| HID wedge vs COM | Lưu ý bổ sung → mục 1; Task 6 |
| Health beep không gây khó chịu | Lưu ý bổ sung → mục 3; Task 7 |

**2. Placeholder scan:** Không dùng TBD; Task 6 ghi rõ deferred nếu chưa implement listener.

**3. Type consistency:** Field `AppConfig` khớp `normalize_config` và settings dialog.

---

## Execution handoff

**Plan complete and saved to `docs/superpowers/plans/2026-04-07-background-tray-headless-mode.md`. Two execution options:**

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration. **REQUIRED SUB-SKILL:** superpowers:subagent-driven-development.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints. **REQUIRED SUB-SKILL:** superpowers:executing-plans.

**Which approach?**
