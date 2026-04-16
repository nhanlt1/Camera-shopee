# Pack Recorder UI/UX Simplification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Triển khai thiết kế trong `docs/superpowers/specs/2026-04-16-ui-ux-simplification-design.md`: tab Quầy / Quản lý (không dừng worker khi đổi tab), Mini-Overlay hai quầy khi minimize/ẩn, Wizard thiết lập + QR Winson, nhóm Settings ba mã Winson, cờ cấu hình và luồng kiosk/onboarding, không dùng PIN để vào Setup.

**Architecture:** Giữ `OrderStateMachine`, `SerialScanWorker`, `MpCameraPipeline` là nguồn sự thật; UI chỉ đổi lớp hiển thị (`QTabWidget`, overlay). Tách widget tìm kiếm khỏi `QDialog` để nhúng tab. Thêm `MiniStatusOverlay` (`QWidget` + `WindowStaysOnTopHint` + `FramelessWindowHint`) đồng bộ qua signal/timer từ `MainWindow`. Wizard dùng `QWizard` hoặc `QStackedWidget` + bước cố định, ghi `AppConfig` và cờ `onboarding_complete` / `first_run_setup_required`.

**Tech Stack:** Python 3.x, PySide6 (`QtWidgets`, `QtCore`, `QtGui`), `pyserial`, pytest, có sẵn `RecordingIndex`, `docs/scanner-config-codes/winson-mode-barcodes/*.png`.

---

## Phạm vi & cách đọc plan

Spec gồm nhiều phần độc lập (tab, overlay, wizard, settings QR, startup). Plan này là **một** tài liệu triển khai theo thứ tự phụ thuộc; nếu cần ship từng phần, ưu tiên: **Task 1 → 2 → 3 → 4** (config + tab + không regression worker) trước Wizard/Overlay lớn.

---

## Bản đồ file (trước khi làm task)

| File | Trách nhiệm sau refactor |
|------|---------------------------|
| `src/packrecorder/config.py` | `AppConfig`: cờ `first_run_setup_required`, `onboarding_complete`, `default_to_kiosk`, `kiosk_fullscreen_on_start`, `mini_overlay_*`, `windows_startup_hint_shown`; bump `schema_version` nếu cần migrate rõ. |
| `src/packrecorder/ui/main_window.py` | `QTabWidget` dưới menu bar; tab Quầy = nội dung hiện tại (`QStackedWidget` / `DualStationWidget`); tab Quản lý = widget tìm kiếm; **không** gọi `_cleanup_workers` / `_stop_serial_workers` khi đổi tab; xử lý `showMinimized` / `hide` → hiện overlay; menu Tệp: Wizard + (tuỳ chọn) mở tab Quản lý thay cho modal chính. |
| `src/packrecorder/ui/recording_search_dialog.py` | Tách nội dung thành `RecordingSearchPanel(QWidget)` (hoặc tên tương đương); `RecordingSearchDialog` bọc panel + nút đóng; tab dùng cùng panel. |
| `src/packrecorder/ui/mini_status_overlay.py` (mới) | Cửa sổ nổi: 2 dòng Máy 1/2, màu + text trạng thái + mã đơn khi đang ghi; double-click → `MainWindow.showNormal()` + `raise_()` + `activateWindow()`. |
| `src/packrecorder/ui/setup_wizard.py` (mới) | Luồng 12.2: số quầy → camera → máy quét (nhánh QR `881001133.`) → tên → lặp Máy 2 → hoàn tất. |
| `src/packrecorder/ui/dual_station_widget.py` | Chế độ **Kiosk**: ẩn khối USB/RTSP/COM/HID/ROI khi `kiosk_mode` bật; chỉ preview + chip + tên + mã đơn + nút ghi; chi tiết qua Wizard/Settings. |
| `src/packrecorder/ui/settings_dialog.py` | Nhóm «Máy quét / mã Winson»: radio COM / HID / Keyboard → hiển thị đúng một QR + chuỗi; đường dẫn ảnh từ `docs/scanner-config-codes/winson-mode-barcodes/`. |
| `src/packrecorder/app.py` | Sau `show()`: nếu `kiosk_fullscreen_on_start` và đa quầy → `showFullScreen` (hoặc tương đương); gọi kiểm tra mở Wizard khi `first_run_setup_required`. |
| `tests/test_config.py` | Roundtrip + default cho field mới. |
| `tests/test_recording_search_embed.py` (mới, tùy) | Khởi tạo panel không crash, không `exec` modal. |
| `tests/test_mini_overlay.py` (mới, tùy) | Pure logic format text / mapping màu nếu tách hàm thuần. |

---

### Task 1: `AppConfig` — cờ UI / onboarding / overlay

**Files:**
- Modify: `src/packrecorder/config.py` (`AppConfig`, `normalize_config`, có thể `schema_version`)
- Test: `tests/test_config.py`

**Hằng số Winson (dùng chung UI + test, tránh typo):**

```python
# Trong config.py hoặc module nhỏ packrecorder/winson_scanner_codes.py — chọn một nơi và import lại ở wizard/settings
WINSON_MODE_USB_COM = "881001133."
WINSON_MODE_USB_HID = "881001131."
WINSON_MODE_USB_KEYBOARD = "881001124."
```

- [ ] **Step 1: Viết test thất bại cho field mới**

Thêm vào `tests/test_config.py`:

```python
def test_ui_simplification_flags_defaults() -> None:
    from packrecorder.config import AppConfig, normalize_config

    c = normalize_config(AppConfig())
    assert c.first_run_setup_required is True
    assert c.onboarding_complete is False
    assert c.default_to_kiosk is True
    assert c.kiosk_fullscreen_on_start is False
    assert c.mini_overlay_enabled is True
    assert c.mini_overlay_click_through is False
    assert c.mini_overlay_corner == "bottom_right"
    assert c.windows_startup_hint_shown is False
```

- [ ] **Step 2: Chạy test — kỳ vọng FAIL**

Run: `cd c:\Users\nhanl\Documents\Camera-shopee; python -m pytest tests/test_config.py::test_ui_simplification_flags_defaults -v`

Expected: `AttributeError` hoặc assertion fail trên field chưa có.

- [ ] **Step 3: Thêm field vào `AppConfig` và chuẩn hoá**

Trong `AppConfig` (sau các field tray hiện có, khoảng sau dòng `video_retention_keep_days`), thêm:

```python
    # UI simplification / kiosk / wizard (spec 2026-04-16)
    first_run_setup_required: bool = True
    onboarding_complete: bool = False
    default_to_kiosk: bool = True
    kiosk_fullscreen_on_start: bool = False
    mini_overlay_enabled: bool = True
    mini_overlay_click_through: bool = False
    mini_overlay_corner: str = "bottom_right"
    windows_startup_hint_shown: bool = False
```

Trong `normalize_config`, trước `return cfg` (hoặc cuối hàm), thêm gán bool/str an toàn:

```python
    cfg.first_run_setup_required = bool(cfg.first_run_setup_required)
    cfg.onboarding_complete = bool(cfg.onboarding_complete)
    cfg.default_to_kiosk = bool(cfg.default_to_kiosk)
    cfg.kiosk_fullscreen_on_start = bool(cfg.kiosk_fullscreen_on_start)
    cfg.mini_overlay_enabled = bool(cfg.mini_overlay_enabled)
    cfg.mini_overlay_click_through = bool(cfg.mini_overlay_click_through)
    corner = str(cfg.mini_overlay_corner or "").strip().lower()
    cfg.mini_overlay_corner = corner if corner in ("bottom_right", "bottom_left", "top_right", "top_left") else "bottom_right"
    cfg.windows_startup_hint_shown = bool(cfg.windows_startup_hint_shown)
```

Tăng `schema_version` từ `8` lên `9` nếu team muốn phân biệt file cũ; nếu không bump, các field vẫn có default qua dataclass khi `load_config` merge key.

- [ ] **Step 4: Chạy test — kỳ vọng PASS**

Run: `python -m pytest tests/test_config.py::test_ui_simplification_flags_defaults -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/packrecorder/config.py tests/test_config.py
git commit -m "feat(config): add UI simplification and mini-overlay flags"
```

---

### Task 2: `RecordingSearchPanel` — tách nội dung khỏi dialog để nhúng tab

**Files:**
- Modify: `src/packrecorder/ui/recording_search_dialog.py`
- Test: `tests/test_recording_search_dialog.py` (mở rộng)

- [ ] **Step 1: Đổi tên / tách class**

Tạo class `RecordingSearchPanel(QWidget)` chứa toàn bộ layout hiện tại của `RecordingSearchDialog` (bảng, filter, nút — **không** gồm `QDialogButtonBox` Đóng nếu tab không cần; có thể giữ nút «Đóng» chỉ trong dialog).

Constructor giữ chữ ký tương thích logic:

```python
class RecordingSearchPanel(QWidget):
    def __init__(
        self,
        config: AppConfig,
        office_search_stale: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        # ... di chuyển code __init__ từ RecordingSearchDialog ...
```

`RecordingSearchDialog.__init__` tạo `vertical = QVBoxLayout(self)` → `self._panel = RecordingSearchPanel(...)` → `layout.addWidget(self._panel)` → nút đóng `QDialogButtonBox`.

- [ ] **Step 2: Test nhỏ — panel khởi tạo được**

Thêm vào `tests/test_recording_search_dialog.py`:

```python
from PySide6.QtWidgets import QApplication

from packrecorder.config import AppConfig, normalize_config
from packrecorder.ui.recording_search_dialog import RecordingSearchPanel


def test_recording_search_panel_instantiates(qtbot):
    _ = QApplication.instance() or QApplication([])
    cfg = normalize_config(AppConfig())
    p = RecordingSearchPanel(cfg, office_search_stale=False)
    p.show()
    qtbot.addWidget(p)
    assert p.isVisible()
```

Cần `pytest-qt` (`qtbot`); nếu project chưa có `pytest-qt`, dùng test không GUI:

```python
def test_recording_search_panel_import():
    from packrecorder.ui.recording_search_dialog import RecordingSearchPanel
    assert RecordingSearchPanel is not None
```

- [ ] **Step 3: Chạy pytest**

Run: `python -m pytest tests/test_recording_search_dialog.py -v`

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/packrecorder/ui/recording_search_dialog.py tests/test_recording_search_dialog.py
git commit -m "refactor(ui): extract RecordingSearchPanel for tab embedding"
```

---

### Task 3: `MainWindow` — `QTabWidget` Quầy | Quản lý (6.2a)

**Files:**
- Modify: `src/packrecorder/ui/main_window.py` (khởi tạo UI: chỗ gắn `_stack` / `_dual_panel`)
- Modify: có thể `src/packrecorder/ui/recording_search_dialog.py` (export panel)

**Nguyên tắc:** `currentChanged` của tab **chỉ** có thể:
- tạm dừng **vẽ preview** (tuỳ chọn, qua flag `_preview_visible` gọi `update()` / không copy frame vào label) — **không** gọi `stop_worker`, `pl.stop()`, `_stop_serial_workers`, `_cleanup_workers`.

- [ ] **Step 1: Tìm chỗ tạo `_stack` và `setCentralWidget`**

Đọc `main_window.py` phần `__init__` (khoảng dòng 200–400 tùy file) để xác định biến: `_stack: QStackedWidget`, `_dual_panel: DualStationWidget`.

- [ ] **Step 2: Bọc central bằng tab**

Pseudo-cấu trúc (điều chỉnh tên biến cho khớp code thực tế):

```python
from PySide6.QtWidgets import QTabWidget

self._main_tabs = QTabWidget(self)
self._main_tabs.addTab(self._stack, "Quầy")
self._search_panel = RecordingSearchPanel(self._config, office_search_stale=self._office_search_stale, parent=self)
self._main_tabs.addTab(self._search_panel, "Quản lý")
self.setCentralWidget(self._main_tabs)
```

**Không** gọi `setFocus()` lên ô tìm kiếm trong slot `currentChanged` (spec 6.2a).

- [ ] **Step 3: Sửa `_open_recording_search`**

Thay `dlg.exec()` bằng chuyển tab và optional raise:

```python
def _open_recording_search(self) -> None:
    self._note_user_activity()
    idx = self._main_tabs.indexOf(self._search_panel)
    if idx >= 0:
        self._main_tabs.setCurrentIndex(idx)
```

- [ ] **Step 4: Menu Tệp**

Đổi copy: giữ mục mở tìm kiếm như **lối phụ** «Mở tab Quản lý» (cùng handler trên).

- [ ] **Step 5: Kiểm tra tay**

Run app: `python -m packrecorder` hoặc entry point trong `pyproject.toml`. Chuyển tab Quản lý trong lúc COM đang kết nối — quét vẫn nhận (quan sát log hoặc trạng thái ghi). Không có test tự động bắt buộc nếu chưa có harness GUI.

- [ ] **Step 6: Commit**

```bash
git add src/packrecorder/ui/main_window.py
git commit -m "feat(ui): add Quầy and Management tabs without stopping workers"
```

---

### Task 4: `DualStationWidget` — chế độ Kiosk (ẩn form thiết bị trên Quầy)

**Files:**
- Modify: `src/packrecorder/ui/dual_station_widget.py`
- Modify: `src/packrecorder/ui/main_window.py` (truyền `kiosk_mode` từ config: `default_to_kiosk and onboarding_complete`)

- [ ] **Step 1: Thêm tham số `kiosk_mode: bool` vào `DualStationWidget.__init__`**

Khi `kiosk_mode` True và `multi_camera_mode == "stations"`:
- Ẩn (`.setVisible(False)`) các `QGroupBox` / form chứa USB/RTSP/COM/HID/ROI — **giữ** preview, banner thời lượng, hàng mã đơn + chip trạng thái, nhãn tên quầy (theo spec 11.1).

Cách an toàn: gom các widget «thiết bị» vào một `QWidget` container `_device_form` và `setVisible(not kiosk_mode)`.

- [ ] **Step 2: Nút «Thiết lập máy & quầy»**

Trên header quầy (trong `MainWindow` hoặc đỉnh `DualStationWidget`): `QPushButton` kết nối `self._open_setup_wizard` (Task 6). Nhãn đúng spec 12.1: «Thiết lập máy & quầy».

- [ ] **Step 3: Commit**

```bash
git add src/packrecorder/ui/dual_station_widget.py src/packrecorder/ui/main_window.py
git commit -m "feat(ui): kiosk layout hides device controls on counter view"
```

---

### Task 5: `MiniStatusOverlay` — hai dòng trạng thái (6.2b)

**Files:**
- Create: `src/packrecorder/ui/mini_status_overlay.py`
- Modify: `src/packrecorder/ui/main_window.py`
- Test: `tests/test_mini_overlay_text.py` (hàm thuần nếu tách `format_station_line`)

- [ ] **Step 1: Implement overlay**

```python
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


class MiniStatusOverlay(QWidget):
    request_restore_main = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(
            parent,
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint,
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        lay = QVBoxLayout(self)
        self._line1 = QLabel("Máy 1: —")
        self._line2 = QLabel("Máy 2: —")
        for lb in (self._line1, self._line2):
            f = QFont()
            f.setPointSize(10)
            lb.setFont(f)
        lay.addWidget(self._line1)
        lay.addWidget(self._line2)
        self._click_through = False

    def set_click_through(self, on: bool) -> None:
        self._click_through = on
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, on)

    def mouseDoubleClickEvent(self, event) -> None:
        if not self._click_through:
            self.request_restore_main.emit()
        super().mouseDoubleClickEvent(event)
```

Nối `overlay.request_restore_main` trong `MainWindow` tới slot gọi `showNormal()`, `raise_()`, `activateWindow()`, và `overlay.hide()`.

- [ ] **Step 2: Vị trí góc dưới phải**

Trong `MainWindow`, method `_position_mini_overlay`:

```python
def _position_mini_overlay(self) -> None:
    geo = self.screen().availableGeometry() if self.screen() else self.geometry()
    m = 12
    self._mini_overlay.adjustSize()
    sz = self._mini_overlay.sizeHint()
    x = geo.right() - sz.width() - m
    y = geo.bottom() - sz.height() - m
    self._mini_overlay.move(x, y)
```

Gọi từ `resizeEvent` / sau `show` overlay.

- [ ] **Step 3: Hiện overlay khi main minimize / hide**

Trong `changeEvent` hoặc override `hideEvent` của `MainWindow`:

```python
def changeEvent(self, event: QEvent) -> None:
    super().changeEvent(event)
    if event.type() != QEvent.Type.WindowStateChange:
        return
    if not self._config.mini_overlay_enabled:
        return
    if self._config.multi_camera_mode != "stations":
        return
    st = self.windowState()
    if st & Qt.WindowState.WindowMinimized or not self.isVisible():
        self._mini_overlay.update_lines_from_main(self)
        self._position_mini_overlay()
        self._mini_overlay.show()
    else:
        self._mini_overlay.hide()
```

**Lưu ý:** `update_lines_from_main` cần đọc trạng thái từ `MainWindow` (order label, recording state per station) — map từ các thuộc tính hiện có (`_order_state` / label station; grep `Máy 1` / `station` trong `main_window.py`).

- [ ] **Step 4: `mini_overlay_click_through`**

Khi bật trong Settings (Task 7), gọi `set_click_through(True)` và bật cảnh báo trong UI: double-click không hoạt động cho đến khi tắt click-through hoặc dùng khay.

- [ ] **Step 5: Commit**

```bash
git add src/packrecorder/ui/mini_status_overlay.py src/packrecorder/ui/main_window.py
git commit -m "feat(ui): floating mini overlay for two-station status when minimized"
```

---

### Task 6: `SetupWizard` — luồng 12.2 + QR khi không có COM (6.3)

**Files:**
- Create: `src/packrecorder/ui/setup_wizard.py`
- Modify: `src/packrecorder/app.py` hoặc `main_window.py` — hiện wizard khi `first_run_setup_required and not onboarding_complete`
- Reuse: `src/packrecorder/ui/hid_pos_setup_wizard.py` khi user chọn HID (theo spec 5)

- [ ] **Step 1: Skeleton `QWizard`**

```python
from PySide6.QtWidgets import QWizard, QWizardPage


class SetupWizard(QWizard):
    def __init__(self, config: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Thiết lập quầy")
        self._config = config
        self.addPage(WelcomeStationCountPage())
        # ... các page: camera, scanner + QR branch, name, repeat for station 2, finish
```

- [ ] **Step 2: Nhánh lỗi COM**

Trên trang máy quét: nếu sau `refresh_serial_ports()` (hoặc hàm tương đương trong codebase) danh sách COM rỗng, hiển thị `QLabel` văn bản hướng dẫn + `QLabel` với `QPixmap` load từ:

`Path(__file__).resolve().parents[3] / "docs" / "scanner-config-codes" / "winson-mode-barcodes" / "qr-usb-com.png"`

(Điều chỉnh số `parents` theo vị trí file trong repo; hoặc dùng `importlib.resources` nếu đóng gói.)

Chuỗi hiển thị: `881001133.`

- [ ] **Step 3: Hoàn tất**

Ghi `save_config`, set `onboarding_complete = True`, `first_run_setup_required = False`, `normalize_config`, đóng wizard, emit signal cho `MainWindow` restart workers (`_restart_scan_workers`).

- [ ] **Step 4: Menu**

Thêm action «Trình hướng dẫn thiết lập quầy…» → `exec` wizard.

- [ ] **Step 5: Commit**

```bash
git add src/packrecorder/ui/setup_wizard.py src/packrecorder/ui/main_window.py src/packrecorder/app.py
git commit -m "feat(ui): setup wizard with Winson COM QR fallback"
```

---

### Task 7: `SettingsDialog` — nhóm ba mã Winson (6.3a)

**Files:**
- Modify: `src/packrecorder/ui/settings_dialog.py`

- [ ] **Step 1: Nhóm QWidget mới «Máy quét / mã Winson»**

`QButtonGroup` + 3 `QRadioButton`: USB COM / USB HID / USB Keyboard.

Slot `idClicked`: hiển thị `QStackedWidget` hoặc thay `QLabel` pixmap + `QLabel` text:

| Lựa chọn | Chuỗi | File PNG |
|----------|--------|----------|
| COM | `881001133.` | `qr-usb-com.png` |
| HID | `881001131.` | `qr-usb-hid.png` |
| Keyboard | `881001124.` | `qr-usb-keyboard.png` |

- [ ] **Step 2: Commit**

```bash
git add src/packrecorder/ui/settings_dialog.py
git commit -m "feat(settings): Winson mode QR codes for COM, HID, and Keyboard"
```

---

### Task 8: Khởi động Windows — nút tạo shortcut (6.4)

**Files:**
- Create: `scripts/create_startup_shortcut.py` hoặc method trong Settings gọi `win32com.client` / PowerShell — **ưu tiên** không ghi Registry silently; tạo `.lnk` trong `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`.

Ví dụ PowerShell từ Python:

```python
import os
import subprocess
from pathlib import Path

def create_startup_shortcut(target_exe: Path) -> None:
    startup = Path(os.environ["APPDATA"]) / r"Microsoft\Windows\Start Menu\Programs\Startup"
    startup.mkdir(parents=True, exist_ok=True)
    lnk = startup / "Pack Recorder.lnk"
    ps = (
        f'$s=(New-Object -ComObject WScript.Shell).CreateShortcut({str(lnk)!r});'
        f'$s.TargetPath={str(target_exe)!r};$s.WorkingDirectory={str(target_exe.parent)!r};$s.Save()'
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
```

- [ ] **Step 1:** Nút trong Wizard hoặc Settings «Tạo lối tắt khởi động» gọi hàm trên với `sys.executable` hoặc đường dẫn `.exe` build.

- [ ] **Step 2:** `windows_startup_hint_shown` — hiện `QMessageBox` hướng dẫn một lần.

- [ ] **Step 3: Commit**

```bash
git add scripts/create_startup_shortcut.py src/packrecorder/ui/settings_dialog.py
git commit -m "feat(windows): optional Startup folder shortcut for Pack Recorder"
```

---

### Task 9: Full screen khi mở + Esc (6.2, §10)

**Files:**
- Modify: `src/packrecorder/app.py`, `src/packrecorder/ui/main_window.py`

- [ ] **Step 1:** Sau `main_window.show()`, nếu `config.kiosk_fullscreen_on_start` và `multi_camera_mode == "stations"` và `onboarding_complete`: `main_window.showFullScreen()`.

- [ ] **Step 2:** `keyPressEvent` / `QShortcut`: phím `Esc` trong fullscreen → `QMessageBox.question` «Thoát toàn màn hình?» — Yes → `showNormal()`.

- [ ] **Step 3: Commit**

```bash
git add src/packrecorder/app.py src/packrecorder/ui/main_window.py
git commit -m "feat(ui): optional fullscreen on start with Esc confirmation"
```

---

### Task 10: Khay — tooltip phụ (11.4)

**Files:**
- Modify: `src/packrecorder/ui/main_window.py` (nơi tạo `QSystemTrayIcon`)

Cập nhật `setToolTip` với hai dòng trạng thái tóm tắt (copy logic từ overlay) để khớp spec «dự phòng».

- [ ] **Commit:** `git commit -m "chore(tray): align tooltip with two-line station summary"`

---

## Kiểm thử chấp nhận (manual QA — spec 6.6)

| Kiểm tra | Cách |
|-----------|------|
| Tab Quản lý không dừng ghi/COM | Bật ghi, chuyển tab, quét tiếp — file video hoặc trạng thái không đứt. |
| Minimize — overlay 2 dòng | Minimize cửa sổ, quan sát góc phải dưới. |
| Wizard lần đầu | Xoá `onboarding_complete` trong config test, mở app — wizard hiện. |
| Settings — 3 QR | Đổi radio, đúng ảnh/chuỗi. |

---

## Self-review (theo skill)

**1. Spec coverage**

| Mục spec | Task |
|----------|------|
| 6.1 cờ config | Task 1 |
| 6.2a tab | Task 3 |
| 6.2 kiosk | Task 4 |
| 6.2b Mini-Overlay | Task 5 |
| 6.3 Wizard + QR COM | Task 6 |
| 6.3a Settings 3 QR | Task 7 |
| 6.4 Startup shortcut | Task 8 |
| 6.5 lỗi thân thiệi | Task 4–6 (chip lỗi — bổ sung message trong kiosk nếu thiếu) |
| 7.x Winson / COM | Task 1 hằng số + Task 6–7 |
| 11–12 Wizard entry | Task 6, menu Task 3/6 |
| §10 tab không pause worker | Task 3 (explicit không gọi cleanup) |

**2. Placeholder scan:** Không dùng TBD/TODO trong plan; các đoạn «grep / đọc» là hướng dẫn mở file thực tế.

**3. Type consistency:** `RecordingSearchPanel` nhận `AppConfig`; overlay gọi `update_lines_from_main(self)` — khi implement đặt tên method cố định trong Task 5.

**Gap có thể bổ sung sau:** i18n đầy đủ (ngoài phạm vi §8); render barcode 1D (spec nói không bắt buộc).

---

Plan complete and saved to `docs/superpowers/plans/2026-04-16-ui-ux-simplification-implementation.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
