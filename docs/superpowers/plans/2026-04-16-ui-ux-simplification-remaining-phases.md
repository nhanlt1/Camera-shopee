# Pack Recorder UI/UX — Remaining Phases Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hoàn thiện các mục trong `docs/superpowers/specs/2026-04-16-ui-ux-simplification-design.md` **chưa có UI hoặc chưa đủ độ sâu** sau phase 1 (tab Quầy/Quản lý, kiosk cơ bản, wizard QR COM) và phase 2 (paint preview, mini-overlay + click-through, QWizard). Trọng tâm: **Cài đặt** cho cờ vận hành Quầy, **góc overlay**, **mở Wizard từ Cài đặt**, **gợi ý khởi động Windows một lần**, và (tuỳ ưu tiên) **mở rộng Wizard / ẩn ROI theo ngữ cảnh**.

**Architecture:** `AppConfig` đã có đủ field (`default_to_kiosk`, `kiosk_fullscreen_on_start`, `mini_overlay_corner`, `windows_startup_hint_shown`, …) trong `src/packrecorder/config.py`; phần còn lại là **đọc/ghi qua `SettingsDialog.result_config()`** và vài hook trong `MainWindow` (callback mở Wizard, gợi ý startup). Wizard sâu hơn (HID / đọc camera / RTSP) tách **task riêng** để không phá luồng COM đã ổn định.

**Tech Stack:** PySide6, `dataclasses.replace`, pytest, pytest-qt (nếu test nút Settings).

---

## Đối chiếu nhanh: đã có trong code (không lặp task)

| Spec | Trạng thái |
|------|------------|
| §6.2a Tab Quầy / Quản lý + không dừng worker | Đã có `QTabWidget`; paint preview gate (`preview_tab_policy`) |
| §6.2b Mini-Overlay hai dòng + cấu hình bật/tắt + click-through | Đã có `MiniStatusOverlay` + nhóm Mini-Overlay trong Cài đặt (phase 2) |
| §6.3a Ba chế độ Winson + QR trong Settings | Đã có `QGroupBox` Winson + radio COM/HID/Keyboard + ảnh QR |
| §12.1 (2)(3)(5) Menu / nút header / khay mở Wizard | Đã có `Tệp` → wizard, nút header, context menu khay «Thiết lập quầy…» |
| §6.1 / §11 Kiosk ẩn form trên Quầy | Đã có `_kiosk_counter_ui()` + `DualStationWidget.set_kiosk_mode` |
| Tự mở Wizard lần đầu | Đã có `defer_first_run_setup_if_needed` trong `app.py` |
| Full screen khi cấu hình | Đã có `defer_kiosk_fullscreen_if_configured` |

---

## Bản đồ file (phase còn lại)

| File | Trách nhiệm |
|------|-------------|
| `src/packrecorder/ui/settings_dialog.py` | Checkbox «Quầy hằng ngày ẩn form thiết bị», «Toàn màn hình khi mở», combo **góc** Mini-Overlay, nút **mở Wizard**; `result_config` bổ sung field; gợi ý startup (gọi từ `MainWindow` hoặc sau nút lối tắt). |
| `src/packrecorder/ui/main_window.py` | Truyền callback vào `SettingsDialog` để đóng Cài đặt rồi mở Wizard; sau lưu Cài đặt áp dụng `set_kiosk_mode` / `defer_kiosk_fullscreen_if_configured` nếu cần; một lần `QMessageBox` gợi ý Startup (khi `not windows_startup_hint_shown`). |
| `tests/test_config.py` | Assert mặc định / normalize cho field mới nếu thêm (thường không cần nếu chỉ bind UI → field có sẵn). |
| `tests/test_settings_dialog_result.py` (mới, nếu chưa có) | Hoặc mở rộng test hiện có: `result_config()` chứa `default_to_kiosk`, `kiosk_fullscreen_on_start`, `mini_overlay_corner` sau khi đổi widget. |
| `src/packrecorder/ui/setup_wizard.py` | (Tùy Task 4) Thêm bước / tùy chọn loại máy quét (COM vs HID vs camera decode), RTSP nâng cao. |
| `src/packrecorder/ui/dual_station_widget.py` | (Tùy Task 5) Nhóm «Nâng cao» hoặc ẩn ROI khi chỉ dùng COM. |

---

### Task 1: Cài đặt — `default_to_kiosk` và `kiosk_fullscreen_on_start` (§6.1 / §11.1)

**Files:**

- Modify: `src/packrecorder/ui/settings_dialog.py` (constructor: tạo `QGroupBox` hoặc thêm vào nhóm «Chế độ camera» / nhóm mới «Quầy hằng ngày»)
- Modify: `src/packrecorder/ui/settings_dialog.py` (`result_config`)
- Modify: `tests/test_config.py` (chỉ nếu thêm assert mới cho field — field đã tồn tại thì có thể bỏ qua)

**Copy gợi ý (tiếng Việt, ngắn):**

- `default_to_kiosk`: «Ẩn chi tiết camera / máy quét trên màn Quầy (chỉ xem preview và trạng thái)» — tooltip: «Tắt để luôn thấy form chỉnh thiết bị trên Quầy như trước. Bật/tắt không xóa cấu hình.»
- `kiosk_fullscreen_on_start`: «Mở app ở chế độ toàn màn hình (đa quầy, sau khi đã thiết lập xong)» — tooltip: «Cần chế độ Đa quầy và đã hoàn tất thiết lập lần đầu.»

- [ ] **Step 1: Thêm widget trong `SettingsDialog.__init__`**

```python
self._kiosk_hide_form = QCheckBox("Ẩn form thiết bị trên Quầy (chế độ hằng ngày)")
self._kiosk_hide_form.setChecked(cfg.default_to_kiosk)
self._kiosk_hide_form.setToolTip(
    "Khi bật và đã hoàn tất thiết lập: chỉ thấy preview + trạng thái; chi tiết thiết bị trong Wizard hoặc Cài đặt."
)
self._kiosk_fullscreen = QCheckBox("Toàn màn hình khi khởi động (sau thiết lập)")
self._kiosk_fullscreen.setChecked(cfg.kiosk_fullscreen_on_start)
self._kiosk_fullscreen.setToolTip(
    "Áp dụng khi chế độ Đa quầy và đã hoàn tất thiết lập lần đầu."
)
```

Đặt hai checkbox trong `QGroupBox("Quầy hằng ngày (đa quầy)")` và `scroll_layout.addWidget(...)` ở vị trí hợp lý (ví dụ sau `mode_box` hoặc sau `common`).

- [ ] **Step 2: Ghi vào `result_config()`**

Trong `replace(self._cfg, ...)`, thêm:

```python
default_to_kiosk=self._kiosk_hide_form.isChecked(),
kiosk_fullscreen_on_start=self._kiosk_fullscreen.isChecked(),
```

- [ ] **Step 3: Chạy test**

Run: `cd c:\Users\nhanl\Documents\Camera-shopee; python -m pytest tests/test_config.py -q`

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/packrecorder/ui/settings_dialog.py
git commit -m "feat(settings): expose kiosk daily UI and fullscreen-on-start toggles"
```

---

### Task 2: Cài đặt — `mini_overlay_corner` (§6.2b / config)

**Files:**

- Modify: `src/packrecorder/ui/settings_dialog.py` (nhóm Mini-Overlay đã có — thêm `QComboBox`)
- Modify: `src/packrecorder/ui/settings_dialog.py` (`result_config`)

- [ ] **Step 1: Thêm combo 4 góc**

```python
self._mini_corner = QComboBox()
for val, label in (
    ("bottom_right", "Dưới phải"),
    ("bottom_left", "Dưới trái"),
    ("top_right", "Trên phải"),
    ("top_left", "Trên trái"),
):
    self._mini_corner.addItem(label, val)
ix = self._mini_corner.findData(cfg.mini_overlay_corner)
self._mini_corner.setCurrentIndex(max(0, ix))
```

Thêm vào `QFormLayout` của `mini_box`: hàng «Vị trí overlay».

- [ ] **Step 2: `result_config`**

```python
corner = str(self._mini_corner.currentData() or "bottom_right")
mini_overlay_corner=corner,
```

(`normalize_config` trong `config.py` đã chuẩn hoá corner — giữ một nguồn sự thật.)

- [ ] **Step 3: Test thủ công / pytest**

Run: `python -m pytest tests/ -q`

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(settings): mini-overlay corner selector"
```

---

### Task 3: Cài đặt — nút «Mở trình hướng dẫn thiết lập quầy…» (§12.1 mục 4)

**Files:**

- Modify: `src/packrecorder/ui/settings_dialog.py` — thêm tham số `on_run_setup_wizard: Callable[[], None] | None = None` và `QPushButton`
- Modify: `src/packrecorder/ui/main_window.py` — trong `_open_settings`, tạo `SettingsDialog(..., on_run_setup_wizard=...)`

**Hành vi:** Bấm nút → **đóng** `SettingsDialog` bằng `reject()` (không lưu thay đổi chưa bấm Lưu — hoặc dùng `QMessageBox` «Bỏ qua thay đổi chưa lưu?» nếu `isWindowModified()` — YAGNI: có thể chỉ `reject()` rồi mở Wizard như spec «chạy lại wizard»).

- [ ] **Step 1: Trong `SettingsDialog.__init__`**

```python
from collections.abc import Callable
# ...
on_run_setup_wizard: Callable[[], None] | None = None,
) -> None:
    # ...
    self._on_run_setup_wizard = on_run_setup_wizard
    btn_wizard = QPushButton("Mở trình hướng dẫn thiết lập quầy…")
    btn_wizard.setToolTip("Đóng Cài đặt và mở Wizard từng bước (camera, máy quét, tên quầy).")
    btn_wizard.clicked.connect(self._emit_run_setup_wizard)
```

```python
def _emit_run_setup_wizard(self) -> None:
    cb = self._on_run_setup_wizard
    self.reject()
    if cb is not None:
        cb()
```

`MainWindow` truyền `cb = lambda: QTimer.singleShot(0, self._open_setup_wizard)` để Wizard mở sau khi vòng lặp xử lý `reject()` xong.

**Lưu ý:** Gọi `reject()` trước `callback` để `exec()` trả `False`; `MainWindow` dùng `QTimer.singleShot(0, self._open_setup_wizard)` để Wizard mở sau khi dialog đóng.

- [ ] **Step 2: Trong `MainWindow._open_settings`**

```python
def _launch_wizard_after_settings_closed(self) -> None:
    QTimer.singleShot(0, self._open_setup_wizard)

dlg = SettingsDialog(
    self._config,
    self,
    on_test_notification=self._on_test_notification,
    on_run_setup_wizard=self._launch_wizard_after_settings_closed,
)
```

- [ ] **Step 3: Chạy pytest**

Run: `python -m pytest tests/ -q`

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(settings): button to open setup wizard from settings"
```

---

### Task 4: `windows_startup_hint_shown` — hộp thoại một lần (§6.4 / §6.1)

**Files:**

- Modify: `src/packrecorder/ui/main_window.py` — sau khi khởi động hoặc sau `_create_windows_startup_shortcut` thành công (ưu tiên: **sau khi user bấm** «Tạo lối tắt…» và thành công — truyền callback từ `SettingsDialog` hoặc kiểm tra trong `MainWindow` không khả thi vì logic trong dialog)

**Cách tối thiểu:** Trong `SettingsDialog._create_windows_startup_shortcut`, sau `QMessageBox.information` thành công, nếu `not self._cfg.windows_startup_hint_shown`: emit / gọi callback `on_startup_hint_ack` hoặc trả về qua flag — **đơn giản hơn:** lưu tạm `self._should_mark_startup_hint = True` và trong `result_config` không đủ vì user có thể không Lưu.

**Khuyến nghị:** Thêm optional callback `on_startup_shortcut_created: Callable[[], None] | None` từ `MainWindow`:

```python
def _on_startup_shortcut_created(self) -> None:
    if self._config.windows_startup_hint_shown:
        return
    self._config = replace(self._config, windows_startup_hint_shown=True)
    save_config(self._config_path, self._config)
    QMessageBox.information(
        self,
        "Khởi động cùng Windows",
        "Đã tạo lối tắt trong thư mục Khởi động. Lần sau đăng nhập Windows, Pack Recorder có thể chạy tự động.",
    )
```

Hoặc chỉ set flag + một dòng trong message hiện có — **không** spam lần sau.

- [ ] **Step 1:** Nối `SettingsDialog._create_windows_startup_shortcut` success path với `parent` cast `MainWindow` hoặc callback — tránh `MainWindow` import trong `settings_dialog`; **dùng callback** `on_startup_shortcut_created: Callable[[], None] | None` trong `__init__`.

- [ ] **Step 2:** `MainWindow` truyền callback cập nhật `self._config`, `save_config`, `windows_startup_hint_shown=True`.

- [ ] **Step 3:** pytest — có thể test thuần `normalize_config` + field bool; UI test tùy chọn.

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(settings): mark windows startup hint as shown once"
```

---

### Task 5 (tùy ưu tiên): Wizard — loại máy quét COM / HID / đọc camera (§6.3 / §12.2 bước 3)

**Files:**

- Modify: `src/packrecorder/ui/setup_wizard.py` — mở rộng `WizardScannerPage` (hoặc tách trang) để chọn `scanner_input_kind` và cổng / HID / nhánh camera decode; tái sử dụng `HidPosSetupWizard` hoặc luồng từ `dual_station_widget` (đừng nhân đôi logic reconnect).

**Nguyên tắc:** Giữ **đường COM mặc định** làm happy path; HID mở dialog con đã có; «đọc bằng camera» gán `decode` trùng `record` và bật ROI sau trong Cài đặt hoặc trang «Tùy chọn».

- [ ] **Step 1:** Viết test tích hợp nhỏ hoặc test thuần mapping `StationConfig` sau khi chọn từng loại (mock không cần GUI nếu tách hàm `apply_scanner_choice(cfg, col, kind, port) -> AppConfig`).

- [ ] **Step 2:** Implement từng nhánh, commit nhỏ.

---

### Task 6 (tùy ưu tiên): `DualStationWidget` — «Nâng cao» / ẩn ROI khi chỉ COM (§4 / §11.5)

**Files:**

- Modify: `src/packrecorder/ui/dual_station_widget.py`

**Ý tưởng:** Khi `scanner_input_kind == "com"` và decode không dùng camera độc lập, thu gọn hàng ROI dưới `QGroupBox` «Nâng cao» hoặc `QToolButton` «Hiện vùng đọc mã (ROI)».

- [ ] **Step 1:** Xác định điều kiện hiện ROI từ `StationConfig` + helper có sẵn (`camera_should_decode_on_index` / tương đương trong `config.py`).

- [ ] **Step 2:** Implement `_refresh_roi_visibility(col)` gọi từ `sync_from_config`.

---

### Task 7 (tùy chọn): Tiêu đề taskbar khi minimize (§6.2b cuối)

**Files:**

- Modify: `src/packrecorder/ui/main_window.py` — trong `changeEvent` / `WindowStateChange`, nếu `isMinimized()`, `setWindowTitle` một dòng tóm tắt hai quầy (gọi cùng logic `_mini_overlay_line_pair` hoặc tách hàm thuần để test).

- [ ] **Step 1:** Hàm thuần `format_taskbar_title(lines: tuple[str, str]) -> str` trong module nhỏ hoặc `mini_status_overlay.py`.

- [ ] **Step 2:** Test đơn vị.

---

## Self-review (tác giả plan)

**1. Spec coverage**

| Yêu cầu spec | Task |
|--------------|------|
| §6.1 cờ kiosk / fullscreen trong Cài đặt | Task 1 |
| §6.2b góc overlay | Task 2 |
| §12.1 (4) Wizard từ Cài đặt | Task 3 |
| §6.4 gợi ý khởi động, không spam | Task 4 |
| §6.3 / §12.2 đầy đủ loại máy quét | Task 5 |
| §4 ROI / overload | Task 6 |
| Taskbar title | Task 7 |

**2. Placeholder scan:** Không dùng TBD; Task 5–7 ghi rõ «tùy ưu tiên».

**3. Type consistency:** `mini_overlay_corner` chỉ nhận bốn chuỗi đã có trong `normalize_config`; `default_to_kiosk` / `kiosk_fullscreen_on_start` trùng tên field `AppConfig`.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-16-ui-ux-simplification-remaining-phases.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
