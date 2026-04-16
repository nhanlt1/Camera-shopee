# Pack Recorder UI/UX — Phase 2 (phần còn lại) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hoàn thiện các điểm spec chưa có trong bản triển khai đầu: (1) **chỉ tắt vẽ preview** khi tab không phải Quầy — worker/pipeline/COM không đổi; (2) **Cài đặt** cho Mini-Overlay: bật/tắt overlay và **click-through** + cảnh báo UX; (3) **Wizard nhiều bước** với nhánh **QR Winson `881001133.`** khi không có cổng COM sau làm mới.

**Architecture:** `MainWindow` giữ cờ `_paint_quay_preview: bool` đồng bộ với `QTabWidget.currentChanged` (index tab Quầy). Đường vẽ preview (`_flush_pending_station_previews` / tùy `_on_worker_preview`) **return sớm** khi cờ false — **không** gọi `_stop_serial_workers` / `MpCameraPipeline.stop`. `SettingsDialog` đọc/ghi `mini_overlay_enabled`, `mini_overlay_click_through` qua `replace(cfg, …)`. Wizard tách thành `QWizard` + `QWizardPage` (hoặc `QStackedWidget` + nút Tiếp/Lùi) và một widget `WinsonComQrPanel` tái sử dụng ảnh `docs/scanner-config-codes/winson-mode-barcodes/qr-usb-com.png`.

**Tech Stack:** PySide6 (`QWizard` / `QWizardPage` hoặc `QStackedWidget`), `packrecorder.serial_ports.list_filtered_serial_ports`, pytest.

---

## Phạm vi phase 2 (đối chiếu spec)

| Spec | Nội dung | Task dưới đây |
|------|-----------|----------------|
| §6.2a cuối | Preview có thể không vẽ khi tab ẩn; capture/worker giữ nguyên | Task 1 |
| §6.2b + §6.1 | `mini_overlay_click_through` trong Cài đặt; cảnh báo khi bật | Task 2 |
| §6.3 + §12.2 | Wizard từng bước; QR `881001133.` khi COM trống | Task 3 |

**Ngoài phạm vi phase 2 (YAGNI / tùy chọn sau):** tiêu đề taskbar khi minimize (§6.2b bổ sung); `windows_startup_hint_shown` một lần; mã vạch 1D trên UI.

---

## Bản đồ file

| File | Thay đổi |
|------|-----------|
| `src/packrecorder/ui/main_window.py` | Cờ paint preview; `currentChanged` trên `_main_tabs`; sửa `_flush_pending_station_previews` (và/hoặc chỗ gọi `set_preview_column`); sau Cài đặt áp dụng `mini_overlay` từ config (đã có một phần). |
| `src/packrecorder/ui/settings_dialog.py` | Nhóm «Mini-Overlay»: `QCheckBox` bật overlay, `QCheckBox` click-through + `QLabel` cảnh báo; `result_config` / khởi tạo từ `cfg`. |
| `src/packrecorder/ui/setup_wizard.py` | Thay dialog một màn bằng wizard nhiều trang; thêm widget nhánh QR. |
| `src/packrecorder/ui/winson_com_qr_panel.py` (mới, tùy) | `QWidget`: ảnh QR + chuỗi `881001133.` + nút gọi callback «Làm mới thiết bị». |
| `tests/test_main_window_preview_tab.py` (mới) | Hàm thuần hoặc mock nhỏ: logic «có vẽ preview hay không» theo index tab. |
| `tests/test_setup_wizard_com_empty.py` (mới, tùy) | Patch `list_filtered_serial_ports` trả `[]` → panel QR hiển thị (nếu test GUI khó thì test helper). |

---

### Task 1: Dừng **vẽ** preview khi không ở tab Quầy (§6.2a)

**Files:**
- Modify: `src/packrecorder/ui/main_window.py` (chỗ tạo `_main_tabs`, `_flush_pending_station_previews`, có thể `_on_worker_preview`)
- Test: `tests/test_main_window_preview_tab.py`

**Nguyên tắc:** Không thêm `stop()`, `pause()`, `hideEvent` trên `DualStationWidget` để dừng worker. Chỉ bỏ qua bước **gán pixmap vào `RoiPreviewLabel`**.

- [ ] **Step 1: Viết test cho helper thuần**

Tạo `src/packrecorder/ui/preview_tab_policy.py` (một hàm — dễ test, không cần `QApplication`):

```python
# src/packrecorder/ui/preview_tab_policy.py
from __future__ import annotations


def should_paint_quay_preview(
    *,
    multi_camera_mode: str,
    main_tab_index: int,
    counter_tab_index: int,
) -> bool:
    if multi_camera_mode != "stations":
        return True
    return main_tab_index == counter_tab_index
```

Tạo `tests/test_main_window_preview_tab.py`:

```python
from packrecorder.ui.preview_tab_policy import should_paint_quay_preview


def test_paint_only_on_counter_tab_for_stations() -> None:
    assert should_paint_quay_preview(
        multi_camera_mode="stations",
        main_tab_index=0,
        counter_tab_index=0,
    )
    assert not should_paint_quay_preview(
        multi_camera_mode="stations",
        main_tab_index=1,
        counter_tab_index=0,
    )


def test_non_stations_always_paints() -> None:
    assert should_paint_quay_preview(
        multi_camera_mode="pip",
        main_tab_index=1,
        counter_tab_index=0,
    )
```

- [ ] **Step 2: Chạy test — kỳ vọng FAIL**

Run: `cd c:\Users\nhanl\Documents\Camera-shopee; python -m pytest tests/test_main_window_preview_tab.py -v`

Expected: `ModuleNotFoundError` hoặc import error cho đến khi tạo file.

- [ ] **Step 3: Thêm file `preview_tab_policy.py`** (nội dung như Step 1).

- [ ] **Step 4: Tích hợp `MainWindow`**

Sau `self._main_tabs.addTab(self._search_panel, "Quản lý")`, lưu index tab Quầy và nối signal:

```python
self._counter_tab_index = self._main_tabs.indexOf(self._counter_page)

def _sync_quay_preview_paint_flag(self) -> None:
    self._paint_quay_preview = should_paint_quay_preview(
        multi_camera_mode=self._config.multi_camera_mode,
        main_tab_index=self._main_tabs.currentIndex(),
        counter_tab_index=self._counter_tab_index,
    )

self._main_tabs.currentChanged.connect(
    lambda _i: self._sync_quay_preview_paint_flag()
)
self._sync_quay_preview_paint_flag()
```

Trong `__init__`, khởi tạo `self._paint_quay_preview = True` trước khi gọi `_sync_quay_preview_paint_flag`.

Trong `_flush_pending_station_previews`, ngay sau khi kiểm tra `multi_camera_mode != "stations"`, thêm:

```python
        if not getattr(self, "_paint_quay_preview", True):
            return
```

**Không** return sớm trong `_on_worker_preview` nếu vẫn muốn gom frame vào `_pending_station_preview` để khi quay lại tab Quầy có frame mới nhất — nếu chọn **không** buffer khi tab lạnh: return sớm trong `_on_worker_preview` luôn (tiết kiệm copy BGR). Plan khuyến nghị: **chỉ skip trong `_flush_pending_station_previews`** để tránh đổi hành vi pipeline; nếu cần tiết kiệm RAM/CPU hơn, bổ sung return trong `_on_worker_preview` ở task follow-up.

- [ ] **Step 5: Chạy test — kỳ vọng PASS**

Run: `python -m pytest tests/test_main_window_preview_tab.py -v`

Expected: PASS

- [ ] **Step 6: Chạy toàn bộ pytest**

Run: `python -m pytest tests/ -q`

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add src/packrecorder/ui/preview_tab_policy.py src/packrecorder/ui/main_window.py tests/test_main_window_preview_tab.py
git commit -m "feat(ui): skip quay preview paint when Management tab is active"
```

---

### Task 2: Cài đặt — Mini-Overlay bật/tắt và click-through (§6.1, §6.2b)

**Files:**
- Modify: `src/packrecorder/ui/settings_dialog.py` (`__init__` gần `tray_box` hoặc sau `winson_box`, `result_config`)
- Modify: `src/packrecorder/ui/main_window.py` (`_open_settings` sau khi lưu: `_sync_mini_overlay_visibility` hoặc đọc lại `mini_overlay_enabled` / `set_click_through`)
- Test: mở rộng `tests/test_config.py` roundtrip (tuỳ chọn) — hoặc chỉ kiểm tay

- [ ] **Step 1: Thêm nhóm UI trong `SettingsDialog`**

Sau `winson_box` (hoặc trước `tray_box`), thêm:

```python
        mini_box = QGroupBox("Cửa sổ nổi trạng thái (Mini-Overlay)")
        mf = QFormLayout(mini_box)
        self._mini_overlay_on = QCheckBox("Bật overlay hai quầy khi thu nhỏ / ẩn cửa sổ")
        self._mini_overlay_on.setChecked(cfg.mini_overlay_enabled)
        self._mini_ct = QCheckBox("Click-through (chuột xuyên qua overlay — khó double-click mở lại app)")
        self._mini_ct.setChecked(cfg.mini_overlay_click_through)
        self._mini_ct_hint = QLabel(
            "Khi bật click-through: ưu tiên mở lại cửa sổ từ khay hoặc tắt tùy chọn này trong Cài đặt."
        )
        self._mini_ct_hint.setWordWrap(True)
        self._mini_ct_hint.setStyleSheet("color:#555;font-size:12px;")
        mf.addRow(self._mini_overlay_on)
        mf.addRow(self._mini_ct)
        mf.addRow(self._mini_ct_hint)
```

Và `scroll_layout.addWidget(mini_box)` đúng thứ tự.

- [ ] **Step 2: `result_config`**

Trong `replace(self._cfg, …)` của `result_config`, thêm:

```python
            mini_overlay_enabled=self._mini_overlay_on.isChecked(),
            mini_overlay_click_through=self._mini_ct.isChecked(),
```

- [ ] **Step 3: `MainWindow` sau khi lưu Cài đặt**

Trong `_open_settings`, sau `save_config` và cập nhật `self._config`, gọi:

```python
                self._mini_overlay.set_click_through(self._config.mini_overlay_click_through)
                if not self._config.mini_overlay_enabled:
                    self._mini_overlay.hide()
                    self._mini_overlay_timer.stop()
                self._sync_mini_overlay_visibility()
```

Đảm bảo `_sync_mini_overlay_visibility` đã tôn trọng `mini_overlay_enabled` (hiện có trong code — nếu chưa, thêm điều kiện `if not self._config.mini_overlay_enabled: hide + stop timer`).

- [ ] **Step 4: Commit**

```bash
git add src/packrecorder/ui/settings_dialog.py src/packrecorder/ui/main_window.py
git commit -m "feat(settings): mini-overlay enable and click-through toggles"
```

---

### Task 3: Wizard nhiều bước + nhánh QR khi COM trống (§6.3, §12.2)

**Files:**
- Modify hoặc replace nội dung: `src/packrecorder/ui/setup_wizard.py`
- Create (khuyến nghị): `src/packrecorder/ui/winson_com_qr_panel.py`
- Modify: `src/packrecorder/app.py` — **không** đổi nếu vẫn gọi `SetupWizardDialog`; chỉ đổi tên class nếu đổi entry
- Test: tùy chọn patch `list_filtered_serial_ports`

**Luồng trang (tối thiểu):**

1. **Chào / số quầy:** `QRadioButton` một hoặc hai quầy → ghi tạm vào bản sao `AppConfig` (`ensure_dual_stations`).
2. **Máy 1 — Camera:** tái sử dụng logic chọn camera giống một phần `DualStationWidget` **hoặc** nhúng một hàng control tối thiểu (combo index + nút thử) — **YAGNI:** có thể giữ một `DualStationWidget` chỉ hiện **cột 0** bằng `setVisible` cột 1 — phức tạp; plan đơn giản hơn: **một `DualStationWidget` full** nhưng **ẩn** toàn bộ cho đến bước «Hoàn tất» từng phần — khó.

**Cách triển khai tối thiểu khả thi:** dùng `QWizard` với `QWizardPage` subclass:

- `PageStationCountWizardPage` — chỉ số quầy.
- `PageStationBlockWizardPage` — lặp `for col in range(n)` trong wizard: dùng **một** widget helper `StationSetupBlock(col)` copy field từ `dual_station_widget` pattern (camera, scanner, name) **hoặc** mở `DualStationWidget` ở **trang cuối** chỉ để chỉnh — không đạt spec.

**Khuyến nghị thực tế:** refactor nhẹ `DualStationWidget` để export **factory** hoặc `StationColumnWidget` một cột — **ngoài phạm vi phase 2 ngắn**. Thay vào đó:

- Trang **«Máy quét — Máy 1»**: `QComboBox` cổng từ `list_filtered_serial_ports()` + nút **«Làm mới thiết bị»** gọi `probe` lại. Nếu `combo.count() == 0` sau refresh: hiện `WinsonComQrPanel` + nhãn hướng dẫn USB COM.

```python
# src/packrecorder/ui/winson_com_qr_panel.py
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from packrecorder.config import WINSON_MODE_USB_COM


class WinsonComQrPanel(QWidget):
    def __init__(self, repo_root: Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        png = repo_root / "docs" / "scanner-config-codes" / "winson-mode-barcodes" / "qr-usb-com.png"
        lay = QVBoxLayout(self)
        self._img = QLabel()
        self._img.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = QPixmap(str(png))
        if not pix.isNull():
            self._img.setPixmap(pix.scaled(200, 200, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))
        self._txt = QLabel(
            f"Không thấy cổng COM. Cần chế độ USB COM — quét mã sau bằng máy Winson:\n{WINSON_MODE_USB_COM}"
        )
        self._txt.setWordWrap(True)
        self._btn = QPushButton("Thử lại / Làm mới thiết bị")
        lay.addWidget(self._img)
        lay.addWidget(self._txt)
        lay.addWidget(self._btn)

    def set_on_refresh(self, callback) -> None:
        self._btn.clicked.connect(callback)
```

- [ ] **Step 1: Tạo `winson_com_qr_panel.py`** (code đầy đủ như trên).

- [ ] **Step 2: Thay `SetupWizardDialog` bằng `QWizard`**

Ví dụ khung đủ chạy (mở rộng thêm trang camera/tên theo §12.2 trong cùng file):

```python
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup,
    QGridLayout,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWizard,
    QWizardPage,
)

from packrecorder.config import AppConfig, ensure_dual_stations, normalize_config


class IntroStationCountPage(QWizardPage):
    def __init__(self, cfg: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setTitle("Số quầy")
        self._cfg = cfg
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel("Chọn số quầy vận hành:"))
        self._g = QButtonGroup(self)
        self._r1 = QRadioButton("Một quầy")
        self._r2 = QRadioButton("Hai quầy")
        self._r2.setChecked(True)
        self._g.addButton(self._r1, 1)
        self._g.addButton(self._r2, 2)
        lay.addWidget(self._r1)
        lay.addWidget(self._r2)

    def validatePage(self) -> bool:
        n = self._g.checkedId()
        if n == 1:
            self._cfg.stations = self._cfg.stations[:1]
        else:
            ensure_dual_stations(self._cfg)
        return True


class SetupWizard(QWizard):
    def __init__(self, cfg: AppConfig, parent=None) -> None:
        super().__init__(parent)
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setWindowTitle("Thiết lập quầy")
        self._cfg = normalize_config(cfg)
        ensure_dual_stations(self._cfg)
        self.addPage(IntroStationCountPage(self._cfg, self))
        # Thêm QWizardPage cho camera → máy quét (có WinsonComQrPanel) → tên → hoàn tất
```

Mỗi trang tiếp theo gọi `registerField` khi cần nút «Tiếp» chỉ bật khi hợp lệ.

- [ ] **Step 3: Trang máy quét — nhánh QR**

Trong `ScannerPage.initializePage` hoặc sau `refresh_ports()`:

```python
from packrecorder.serial_ports import list_filtered_serial_ports

def _refresh_ports(self) -> None:
    ports = list_filtered_serial_ports()
    self._combo.clear()
    # ... điền ports
    self._qr_panel.setVisible(len(ports) == 0)
```

`WinsonComQrPanel.set_on_refresh(self._refresh_ports)`.

- [ ] **Step 4: Cuối wizard — áp dụng config**

Khi `QWizard.Accepted`, gom field → `StationConfig` / `apply_to_config` tương đương `DualStationWidget.apply_to_config` — **có thể** khởi tạo tạm `DualStationWidget` ẩn, set field từ wizard, rồi `apply_to_config` một lần để tránh lệch logic.

- [ ] **Step 5: Cập nhật `MainWindow._open_setup_wizard`**

Đổi `SetupWizardDialog` → `SetupWizard` (hoặc giữ tên file, class mới `SetupWizard`).

- [ ] **Step 6: pytest**

Run: `python -m pytest tests/ -q`

Expected: all pass

- [ ] **Step 7: Commit**

```bash
git add src/packrecorder/ui/setup_wizard.py src/packrecorder/ui/winson_com_qr_panel.py src/packrecorder/ui/main_window.py
git commit -m "feat(ui): multi-step setup wizard with Winson COM QR fallback"
```

---

## Self-review (skill)

**1. Spec coverage (phase 2)**

| Yêu cầu | Task |
|---------|------|
| §6.2a chỉ dừng vẽ preview | Task 1 |
| §6.2b / §6.1 click-through + cấu hình overlay | Task 2 |
| §6.3 + §12 Wizard + QR COM khi lỗi COM | Task 3 |

**2. Placeholder scan:** Không dùng TBD; các đoạn «tùy follow-up» chỉ nằm trong ghi chú kiến trương, không phải bước bắt buộc.

**3. Type consistency:** `should_paint_quay_preview` dùng `counter_tab_index` từ `indexOf(self._counter_page)` — khi thêm/xóa tab phải cập nhật `_counter_tab_index` trong cùng commit.

---

Plan complete and saved to `docs/superpowers/plans/2026-04-16-ui-ux-simplification-phase2.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
