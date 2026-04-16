# Pack Recorder UI/UX — Spec Pending Phases Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Triển khai các phần trong `docs/superpowers/specs/2026-04-16-ui-ux-simplification-design.md` **chưa khớp đầy đủ** sau các phase đã merge (tab + kiosk + wizard COM + Cài đặt Winson 3 QR + mini-overlay + cờ Quầy): **(1)** Wizard chọn **COM / HID POS / đọc mã bằng camera** (§5 B, §6.3 bước 2); **(2)** **Progressive disclosure** ROI/RTSP trên `DualStationWidget` khi không kiosk (§4, Phương án A); **(3)** **Tiêu đề taskbar** khi minimize (§6.2b bổ sung); **(4)** chỉnh **lỗi thân thiện** camera (§6.5) và **audit focus** ô tìm kiếm tab Quản lý (§6.2a).

**Architecture:** Trang máy quét trong `setup_wizard.py` mở rộng bằng **nhóm radio** thay cho chỉ COM; nhánh **HID** tái sử dụng `HidPosSetupWizard` (`exec()` modal con) và ghi `scanner_input_kind="hid_pos"` + `scanner_usb_vid` / `scanner_usb_pid` vào `StationConfig` (cùng mô hình `dual_station_widget.py`). Nhánh **đọc bằng camera** đặt `scanner_serial_port=""`, `decode_camera_index` trùng `record_camera_index` (đồng bộ `normalize_config`). ROI chỉ bắt buộn khi decode camera — logic điều kiện dùng `camera_should_decode_on_index` / `station_for_decode_camera` từ `packrecorder.config`.

**Tech Stack:** PySide6 (`QWizard`, `QRadioButton`, `QButtonGroup`), `pytest`, `dataclasses.replace`.

---

## Đối chiếu spec ↔ trạng thái (tóm tắt)

| Mục spec | Đã có | Chưa / thiếu |
|----------|--------|----------------|
| §6.2a Tab, worker không dừng, preview có thể không vẽ | Có | Audit: focus ô tìm khi chuyển tab |
| §6.2b Mini-overlay + cấu hình | Có | Tiêu đề cửa sổ khi minimize (gợi ý cuối §6.2b) |
| §6.3 Setup: camera → **loại quét (COM/HID/camera)** → tên | Wizard chỉ **COM** + QR `881001133.` | Nhánh HID + đọc camera; RTSP «nâng cao» tuỳ chọn sau |
| §6.3a Winson 3 QR trong Cài đặt | Có | — |
| §4 / Phương án A ROI / RTSP overload | Form đầy đủ khi không kiosk | Thu gọn ROI / RTSP dưới «Nâng cao» |
| §6.5 Lỗi camera thân thiện | Có status một phần | Một dòng + Thử lại + mở Wizard (nếu chưa đủ) |

---

## Bản đồ file

| File | Thay đổi |
|------|-----------|
| `src/packrecorder/ui/setup_wizard.py` | `WizardScannerPage`: radio COM / HID / camera; gọi `HidPosSetupWizard`; `validatePage` cập nhật `StationConfig` đúng nhánh. |
| `src/packrecorder/ui/hid_pos_setup_wizard.py` | Có thể **không** sửa — chỉ `exec()` từ setup wizard; nếu cần `vid_pid_chosen` trước khi `accept`, đọc signal trong parent (xem Task 1 bước 3). |
| `src/packrecorder/ui/dual_station_widget.py` | `QGroupBox` hoặc `QToolButton` «Nâng cao» ẩn/hiện khối RTSP + ROI theo điều kiện. |
| `src/packrecorder/ui/main_window.py` | `changeEvent` / `WindowStateChange`: `setWindowTitle` khi minimize (gọi helper thuần). |
| `src/packrecorder/ui/recording_search_dialog.py` hoặc panel nhúng | Kiểm tra `setFocus` khi hiện tab — tránh auto-focus filter. |
| `tests/test_setup_wizard_scanner_branch.py` (mới) | Test thuần mapping `apply_scanner_branch_to_station(...)` (tách hàm để không cần `QApplication`). |
| `tests/test_taskbar_title_format.py` (mới) | Test `format_minimized_window_title(lines)`. |

---

### Task 1: Wizard — nhánh máy quét COM / HID / đọc camera (§6.3, §5 khuyến nghị B)

**Files:**

- Modify: `src/packrecorder/ui/setup_wizard.py`
- Create: `tests/test_setup_wizard_scanner_branch.py`
- Reference: `src/packrecorder/config.py` — `ScannerInputKind`, `StationConfig`, `replace`, `normalize_config`

**Nguyên tắc:** `scanner_input_kind` trong `config.py` chỉ `"com"` | `"hid_pos"` (xem `ScannerInputKind`). «Đọc mã bằng camera» = **COM rỗng** + decode trùng camera ghi (giống combo «(Chưa chọn — đọc mã bằng camera)» trên quầy).

- [ ] **Step 1: Hàm thuần (module mới hoặc cuối `setup_wizard.py`) — dễ test**

Tạo `src/packrecorder/ui/setup_wizard_scanner.py`:

```python
from __future__ import annotations

from dataclasses import replace

from packrecorder.config import StationConfig


def apply_scanner_choice_com(st: StationConfig, *, port: str) -> StationConfig:
    port = (port or "").strip()
    return replace(
        st,
        scanner_serial_port=port,
        scanner_input_kind="com",
        scanner_usb_vid="",
        scanner_usb_pid="",
    )


def apply_scanner_choice_hid(st: StationConfig, *, vid: str, pid: str) -> StationConfig:
    return replace(
        st,
        scanner_serial_port="",
        scanner_input_kind="hid_pos",
        scanner_usb_vid=vid.strip().upper(),
        scanner_usb_pid=pid.strip().upper(),
    )


def apply_scanner_choice_camera_decode(st: StationConfig) -> StationConfig:
    rec = int(st.record_camera_index)
    return replace(
        st,
        scanner_serial_port="",
        scanner_input_kind="com",
        scanner_usb_vid="",
        scanner_usb_pid="",
        decode_camera_index=rec,
    )
```

- [ ] **Step 2: Test thuần**

```python
from packrecorder.config import StationConfig
from packrecorder.ui.setup_wizard_scanner import (
    apply_scanner_choice_com,
    apply_scanner_choice_hid,
    apply_scanner_choice_camera_decode,
)


def _st() -> StationConfig:
    return StationConfig(
        "sid-a",
        "Máy 1",
        0,
        0,
    )


def test_com_sets_port_and_kind() -> None:
    s = apply_scanner_choice_com(_st(), port="COM3")
    assert s.scanner_input_kind == "com"
    assert s.scanner_serial_port == "COM3"


def test_hid_sets_vid_pid() -> None:
    s = apply_scanner_choice_hid(_st(), vid="1a2b", pid="3c4d")
    assert s.scanner_input_kind == "hid_pos"
    assert s.scanner_usb_vid == "1A2B"


def test_camera_decode_aligns_decode_index() -> None:
    s = apply_scanner_choice_camera_decode(_st())
    assert s.decode_camera_index == s.record_camera_index
```

Run: `python -m pytest tests/test_setup_wizard_scanner_branch.py -v`

Expected: PASS sau khi có module + test.

- [ ] **Step 3: Sửa `WizardScannerPage` trong `setup_wizard.py`**

1. Import `HidPosSetupWizard` từ `packrecorder.ui.hid_pos_setup_wizard`.
2. Import các `apply_scanner_choice_*` từ `setup_wizard_scanner`.
3. Thêm `QRadioButton` / `QButtonGroup`:
   - `USB COM (khuyến nghị)`
   - `HID POS (đọc raw — cấu hình VID/PID)`
   - `Đọc mã bằng camera (không dùng máy quét COM/HID)`
4. Stack widget: khi chọn COM → hiện `QComboBox` + `WinsonComQrPanel` như hiện tại. Khi chọn HID → nút **«Mở thiết lập HID POS…»** gọi:

```python
def _run_hid_wizard(self) -> None:
    wiz = HidPosSetupWizard(self)
    chosen_vid: list[str] = []
    chosen_pid: list[str] = []

    def on_vid_pid(v: int, p: int) -> None:
        chosen_vid[:] = [f"{v:04X}"]
        chosen_pid[:] = [f"{p:04X}"]

    wiz.vid_pid_chosen.connect(on_vid_pid)
    if wiz.exec() and chosen_vid and chosen_pid:
        self._hid_vid = chosen_vid[0]
        self._hid_pid = chosen_pid[0]
        self._lbl_hid_status.setText(f"Đã chọn VID {self._hid_vid} / PID {self._hid_pid}")
```

**Lưu ý:** `HidPosSetupWizard.accept()` (khoảng dòng 258–261) emit `vid_pid_chosen.emit(self._pending_vid, self._pending_pid)` trước `super().accept()` — nối signal như trên là đủ; không cần đọc `chosen_*` sau `exec()` trừ khi muốn kiểm tra `wiz.result()`.

5. `validatePage`:

```python
def validatePage(self) -> bool:
    wiz = self.wizard()
    assert isinstance(wiz, SetupWizard)
    st = wiz._cfg.stations[self._col]
    if self._radio_com.isChecked():
        port = str(self._combo.currentData() or "").strip()
        wiz._cfg.stations[self._col] = apply_scanner_choice_com(st, port=port)
    elif self._radio_hid.isChecked():
        if not getattr(self, "_hid_vid", None) or not getattr(self, "_hid_pid", None):
            QMessageBox.warning(self, "HID", "Chạy «Mở thiết lập HID POS…» và hoàn tất chọn thiết bị.")
            return False
        wiz._cfg.stations[self._col] = apply_scanner_choice_hid(
            st, vid=self._hid_vid, pid=self._hid_pid
        )
    else:
        wiz._cfg.stations[self._col] = apply_scanner_choice_camera_decode(st)
    return True
```

6. `initializePage`: đồng bộ radio từ `wiz._cfg.stations[self._col].scanner_input_kind` và cổng COM hiện có.

- [ ] **Step 4:** `python -m pytest tests/ -q` — Expected: toàn bộ PASS.

- [ ] **Step 5: Commit**

```bash
git add src/packrecorder/ui/setup_wizard.py src/packrecorder/ui/setup_wizard_scanner.py tests/test_setup_wizard_scanner_branch.py
git commit -m "feat(setup-wizard): COM, HID POS, and camera-decode scanner branches"
```

---

### Task 2: `DualStationWidget` — «Nâng cao» cho RTSP + ROI (§4, §11.5)

**Files:**

- Modify: `src/packrecorder/ui/dual_station_widget.py`

- [ ] **Step 1:** Xác định widget chứa hàng RTSP (`_record_kind`, `_rtsp_url`, …) và vùng ROI (`RoiPreviewLabel` / nhãn ROI) — đã có `_apply_record_kind_visibility`.

- [ ] **Step 2:** Thêm `QToolButton` «Nâng cao ▾» trên mỗi cột (hoặc một nút chung): khi `not self._kiosk_mode`, `setCheckable(True)`, `setChecked(False)` mặc định; khi unchecked, ẩn **RTSP radio + URL** (chỉ giữ USB) và ẩn **ROI** nếu `not camera_should_decode_on_index(self._config.stations, cam_idx)` cho camera của cột đó — **hoặc** đơn giản hơn (YAGNI): chỉ ẩn ROI khi `scanner_input_kind == "com"` và cổng COM không rỗng (đọc mã bằng máy quét, không cần ROI).

**Điều kiện tối thiểu an toàn (khớp spec «chỉ quét tay»):** `DualStationWidget` không giữ `self._cfg` — dùng `stations` đối số `sync_from_config(cfg, ...)` hoặc trạng thái combo đã lưu trong `self._scanner_serial` / `self._scanner_kind` (tên thật trong file). Ví dụ logic:

```python
def _should_show_roi_row_for_station(self, st: StationConfig) -> bool:
    if (st.scanner_serial_port or "").strip():
        return False
    if st.scanner_input_kind == "hid_pos":
        return False
    return True
```

Gọi từ `sync_from_config` và khi đổi combo scanner.

- [ ] **Step 3:** `pytest tests/ -q` — regression.

- [ ] **Step 4: Commit**

```bash
git commit -am "feat(dual-station): collapse advanced ROI/RTSP for simple COM users"
```

---

### Task 3: Tiêu đề taskbar khi minimize (§6.2b)

**Files:**

- Create: `src/packrecorder/ui/window_title_summary.py` (hoặc `mini_status_overlay.py` nếu muốn gom)
- Modify: `src/packrecorder/ui/main_window.py`
- Create: `tests/test_taskbar_title_format.py`

- [ ] **Step 1: Hàm thuần**

```python
def format_minimized_window_title(line_a: str, line_b: str, *, max_len: int = 120) -> str:
    base = "Pack Recorder"
    tail = f"{line_a} | {line_b}".strip()
    if not tail.replace("|", "").strip():
        return base
    s = f"{base} — {tail}"
    return s if len(s) <= max_len else s[: max_len - 1] + "…"
```

- [ ] **Step 2: Test**

```python
from packrecorder.ui.window_title_summary import format_minimized_window_title

def test_short_title_unchanged() -> None:
    t = format_minimized_window_title("Máy 1: Chờ", "Máy 2: Chờ")
    assert t.startswith("Pack Recorder —")


def test_empty_fallback() -> None:
    assert format_minimized_window_title("", "") == "Pack Recorder"
```

- [ ] **Step 3: Trong `MainWindow.changeEvent`**, khi `event.type() == WindowStateChange` và `self.isMinimized()` và `multi_camera_mode == "stations"`:

```python
a, b = self._mini_overlay_line_pair()
self.setWindowTitle(format_minimized_window_title(a, b))
```

Khi `windowState()` không còn minimized, `self.setWindowTitle("Pack Recorder")` (hoặc lưu `_saved_title` nếu đã có chỗ khác đổi title).

- [ ] **Step 4:** `pytest tests/ -q`

- [ ] **Step 5: Commit**

```bash
git add src/packrecorder/ui/window_title_summary.py tests/test_taskbar_title_format.py src/packrecorder/ui/main_window.py
git commit -m "feat(ui): taskbar title summary when minimized (stations)"
```

---

### Task 4: §6.5 — Thông báo lỗi camera + §6.2a — Audit focus tìm kiếm

**Files:**

- Modify: `src/packrecorder/ui/main_window.py` hoặc nơi bắt `MpCameraPipeline` / preview lỗi (tìm `_on_mp_worker_error`, status message cho mở camera).
- Modify: `src/packrecorder/ui/recording_search_dialog.py` (hoặc class panel tìm kiếm): đảm bảo **không** `setFocus()` tới ô filter trong `showEvent` khi embed trong tab.

- [ ] **Step 1:** Grep `setFocus`, `focusWidget` trong `recording_search` và tab switch handler.

- [ ] **Step 2:** Nếu có auto-focus, bọc bằng `if reason == UserClickedTab` hoặc bỏ focus khi `event.reason() == ...` — tối thiểu: không gọi `line_edit.setFocus()` trong `showEvent` của panel.

- [ ] **Step 3:** Thêm một dòng status / `QMessageBox` có nút «Mở thiết lập quầy» khi pipeline không mở được camera (copy ngắn tiếng Việt theo §6.5).

- [ ] **Step 4:** `pytest tests/ -q`

- [ ] **Step 5: Commit**

```bash
git commit -am "fix(ui): friendlier camera errors; avoid search focus steal on tab switch"
```

---

## Self-review

**1. Spec coverage**

| Yêu cầu | Task |
|---------|------|
| §6.3 bước 2 COM/HID/camera | Task 1 |
| §4 ROI overload | Task 2 |
| §6.2b taskbar | Task 3 |
| §6.5 + §6.2a focus | Task 4 |

**2. Placeholder scan:** Không có TBD; RTSP trong wizard ghi «tuỳ chọn sau» ngoài scope plan này.

**3. Type consistency:** `scanner_input_kind` chỉ `"com"` | `"hid_pos"`; nhánh camera dùng `apply_scanner_choice_camera_decode` đồng bộ decode với record.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-16-ui-ux-spec-pending-phases.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
