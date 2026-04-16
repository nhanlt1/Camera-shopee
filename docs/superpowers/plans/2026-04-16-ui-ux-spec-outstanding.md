# Pack Recorder UI/UX — Spec Outstanding Work Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hoàn thiện các điểm trong `docs/superpowers/specs/2026-04-16-ui-ux-simplification-design.md` **chưa làm hoặc mới làm một phần** sau chuỗi triển khai (tab Quầy/Quản lý, kiosk, wizard COM/HID/camera, khóa ROI theo loại máy quét, tiêu đề taskbar khi minimize, Cài đặt Winson 3 QR + mini-overlay + cờ Quầy, v.v.).

**Architecture:** Phần còn lại tập trung vào **(1)** Wizard **RTSP** tách khỏi USB (§6.3 «nâng cao»), **(2)** **Nâng cao** đầy đủ trên `DualStationWidget` (ẩn RTSP + ROI khi thu gọn — hiện chỉ có `set_roi_locked`), **(3)** **§6.5** nút «Thử lại» / điều hướng thiết lập khi pipeline camera lỗi, **(4)** tuỳ chọn **mã vạch 1D** cạnh QR Winson (§7.6). Không đụng pipeline multiprocessing lõi (§8 YAGNI).

**Tech Stack:** PySide6, `dataclasses.replace`, `pytest`, logic sẵn có `STATION_RTSP_LOGICAL_ID_BASE` / `station_record_cam_id` trong `src/packrecorder/config.py`.

---

## Trạng thái đối chiếu spec (sau các phase đã merge)

| Mục spec | Trạng thái | Ghi chú |
|----------|------------|---------|
| §6.2a Tab, worker, preview không vẽ khi đổi tab | Đã có | `preview_tab_policy` + comment không focus filter trong `recording_search_dialog.py` |
| §6.2b Mini-overlay, góc, click-through, taskbar title | Đã có | `MiniStatusOverlay`, Cài đặt, `format_minimized_window_title` |
| §6.3 Wizard: camera USB + máy quét COM/HID/camera + QR COM | Đã có | `setup_wizard_scanner.py`, `WizardScannerPage` |
| §6.3 Wizard: **RTSP** (nâng cao) | **Chưa** | `WizardCameraPage` chỉ USB + `record_camera_kind="usb"` |
| §6.3a Winson 3 QR trong Cài đặt | Đã có | Nhóm Winson trong `settings_dialog.py` |
| §4 / §11.5 Thu gọn form: **Nâng cao** RTSP + ROI | **Một phần** | Khóa ROI khi COM/HID; **chưa** nút thu gọn RTSP |
| §6.5 Lỗi camera: dòng thân thiện | Một phần | Đã sửa `showMessage` trong `_on_mp_worker_error`; **chưa** nút «Thử lại» / mở Wizard |
| §7.6 Mã vạch 1D trên UI (tuỳ chọn) | Chưa | Chỉ QR PNG trong repo |
| §11.1 Kiosk ẩn toàn bộ form trên Quầy | Đã có | `default_to_kiosk` + `set_kiosk_mode` |
| §12.1 Điểm vào Wizard (1)–(5) | Đã có / đủ | Tự động, menu, nút header, Cài đặt, khay; overlay double-click → restore main (đúng §12.1 gợi ý) |

---

## Bản đồ file (phần việc còn lại)

| File | Thay đổi |
|------|-----------|
| `src/packrecorder/ui/setup_wizard.py` | `WizardCameraPage`: nhánh RTSP (radio hoặc checkbox), ô URL, ghi `record_camera_kind`, `record_rtsp_url`; `validatePage` + `normalize_config`. |
| `src/packrecorder/ui/dual_station_widget.py` | Lưu tham chiếu `QRadioButton` RTSP vào `self._rb_rtsp: list`; `QToolButton` «Nâng cao» + `_refresh_advanced_visibility`. |
| `src/packrecorder/ui/main_window.py` | Banner nhỏ hoặc `QMessageBox` có nút khi `_on_mp_worker_error`; gọi lại khởi tạo pipeline / `start_background_camera_probe` tùy chỗ an toàn. |
| `src/packrecorder/ui/winson_com_qr_panel.py` hoặc `settings_dialog.py` | (Tuỳ Task 4) Hiển thị ảnh Code128 sinh từ `scripts/generate_winson_mode_qrcodes.py` hoặc file tĩnh. |
| `tests/test_setup_wizard_rtsp_apply.py` (mới) | Hàm thuần `apply_camera_page_rtsp(...)` nếu tách khỏi UI. |

---

### Task 1: Wizard — camera **RTSP** (§6.3, §12.2 bước 2 «nâng cao»)

**Files:**

- Modify: `src/packrecorder/ui/setup_wizard.py` — class `WizardCameraPage`
- Reference: `src/packrecorder/config.py` — `RecordCameraKind`, `STATION_RTSP_LOGICAL_ID_BASE`, `station_record_cam_id` (đọc để gán `decode_camera_index` đồng bộ với `dual_station_widget`)

**Hành vi:** Trên trang camera, thêm:

- `QRadioButton` «USB webcam» (mặc định) | `QRadioButton` «Camera IP (RTSP) — nâng cao».
- Khi RTSP: `QLineEdit` URL (placeholder giống `RTSP_DEFAULT_URL_BY_COLUMN` trong `dual_station_widget.py`), nhãn gợi ý ngắn «Cần mạng ổn định; có thể chỉnh sau trong Cài đặt».
- `validatePage`:

```python
if self._radio_usb.isChecked():
    rd = self._combo.currentData()
    rec = int(rd) if rd is not None else 0
    wiz._cfg.stations[self._col] = replace(
        st,
        record_camera_index=rec,
        decode_camera_index=rec,
        record_camera_kind="usb",
        record_rtsp_url="",
    )
else:
    url = self._rtsp_url.text().strip()
    if not url:
        QMessageBox.warning(self, "RTSP", "Nhập URL RTSP hoặc chọn USB.")
        return False
    wiz._cfg.stations[self._col] = replace(
        st,
        record_camera_kind="rtsp",
        record_rtsp_url=url,
        record_camera_index=0,
        decode_camera_index=STATION_RTSP_LOGICAL_ID_BASE + self._col,
    )
```

Sau đó `normalize_config(wiz._cfg)` trong `accept()` của `SetupWizard` đã có — kiểm tra `ensure_decode_camera_not_peer_record` không phá cấu hình RTSP (đọc `normalize_config` / `ensure_dual_stations`).

- [ ] **Step 1:** Thêm test thuần (tách `apply_wizard_camera_station(...)` vào `setup_wizard_camera.py` nếu muốn TDD) hoặc test nhỏ chỉ `replace` + assert field.

- [ ] **Step 2:** Chạy `python -m pytest tests/ -q` — PASS.

- [ ] **Step 3:** Commit

```bash
git add src/packrecorder/ui/setup_wizard.py tests/test_setup_wizard_rtsp_apply.py
git commit -m "feat(setup-wizard): optional RTSP camera page"
```

---

### Task 2: `DualStationWidget` — nút **«Nâng cao»** thật sự (§4 Phương án A)

**Files:**

- Modify: `src/packrecorder/ui/dual_station_widget.py` — trong `__init__`, sau khi tạo `kind_w` (khối `rb_usb` / `rb_rtsp` đã nằm trong `self._record_kind[col]`).

**Ghi chú code hiện có:** Mỗi cột đã có `QButtonGroup` trong `self._record_kind[col]`; radio RTSP là `self._record_kind[col].button(1)`, USB là `.button(0)`. Ẩn/hiện USB vs RTSP stack đã có `_apply_record_kind_visibility` và `_on_record_kind_changed`.

**Logic mới:**

- Thêm `from PySide6.QtWidgets import QToolButton` (cùng khối import đầu file).
- `self._adv_expanded: list[bool] = [False, False]` và `self._adv_btn: list[QToolButton] = []`.
- Ngay sau `kind_w = QWidget()` / `kind_w.setLayout(kind_box)`, tạo `QToolButton` «Nâng cao (RTSP, ROI đọc mã)», `setCheckable(True)`, đặt cạnh `kind_w` trong một `QHBoxLayout` (USB/RTSP row + nút).
- Trong `apply_config_to_ui` / `sync_from_config` (nơi đã gọi `set_roi_locked` và set radio theo `s.record_camera_kind`), set `self._adv_btn[col].setChecked(True)` khi `s.record_camera_kind == "rtsp"` hoặc `self._preview_roi_unlocked_for_column(col)` là True; ngược lại `False` nếu người dùng chưa từng mở (có thể lưu cờ «đã mở nâng cao» trong bộ nhớ session chỉ bằng list bool, không cần config).
- Hàm `_set_advanced_expanded(self, col: int, on: bool) -> None`:
  - Nếu `on`: hiện toàn bộ `kind_w`, `cw` (stack combo + RTSP), và gọi `_refresh_preview_roi_lock()` cho cột đó.
  - Nếu `not on` và **không** kiosk và **không** phải cấu hình đang RTSP đã lưu (`not (stations[col].record_camera_kind == "rtsp" and (stations[col].record_rtsp_url or "").strip())`): với `QSignalBlocker(self._record_kind[col])` chọn `button(0).setChecked(True)`, gọi `_on_record_kind_changed(col)`, rồi ẩn `kind_w` / phần RTSP tương ứng — **hoặc** đơn giản hơn: khi thu gọn chỉ **ẩn** `rb_rtsp` và hàng URL (`self._rtsp_url[col]`, `self._rtsp_connect_btn[col]`) nhưng giữ USB selected (spec «ẩn RTSP»): `self._record_kind[col].button(1).setVisible(on)` và `self._rtsp_url[col].setVisible(on and self._is_rtsp_column(col))`.

- Kết nối `self._adv_btn[col].toggled` → `_set_advanced_expanded(col, checked)`.

- [ ] **Step 1:** Chạy app, mở Quầy, thu gọn/mở «Nâng cao» — RTSP và ô URL ẩn/hiện đúng; kiosk mode vẫn ẩn cả form qua `_refresh_layout_mode`.

- [ ] **Step 2:** `pytest tests/ -q` — kỳ vọng PASS (không đổi hành vi serialization nếu chỉ UI).

- [ ] **Step 3:** Commit

```bash
git add src/packrecorder/ui/dual_station_widget.py
git commit -m "feat(dual-station): advanced toggle for RTSP and ROI"
```

---

### Task 3: §6.5 — Lỗi camera: **Thử lại** + gợi ý mở Wizard

**Files:**

- Modify: `src/packrecorder/ui/main_window.py` — method `_on_mp_worker_error` (khoảng dòng 1140) và `__init__` (thêm biến cooldown).

**Luồng gọi:** `_on_mp_worker_error` chỉ chạy từ `_mp_service_tick` (timer Qt) — **thread chính UI**, an toàn cho `QMessageBox`.

**Retry:** Trong codebase đã có `_restart_scan_workers()` (khoảng dòng 1518): dừng toàn bộ pipeline/serial workers rồi khởi động lại theo config — **cùng hành vi** watchdog (dòng 987–988: `pl.stop()` rồi `QTimer.singleShot(0, self._restart_scan_workers)`). Không cần hàm `_retry_mp_camera_after_error` riêng: nút «Thử lại» gọi `QTimer.singleShot(0, self._restart_scan_workers)`.

**Tránh spam popup:** Trong `MainWindow.__init__`, thêm:

```python
self._mp_worker_error_dialog_last_mono: dict[int, float] = {}
```

Trong `_on_mp_worker_error`, **giữ nguyên** `append_session_log`, `showMessage`, `_set_tray_icon_error` trước. **Sau đó** mới áp cooldown chỉ cho hộp thoại (log/status vẫn mỗi lần lỗi):

```python
import time
now = time.monotonic()
last = self._mp_worker_error_dialog_last_mono.get(cam_idx, 0.0)
if now - last < 45.0:
    return
self._mp_worker_error_dialog_last_mono[cam_idx] = now
reply = QMessageBox.question(
    self,
    "Camera không mở được",
    f"Camera {cam_idx}: thử lại mở thiết bị hoặc vào Tệp → «Thiết lập máy & quầy» để đổi camera/URL RTSP.\n"
    "Bấm «Thử lại» để khởi động lại toàn bộ luồng camera (giống watchdog).",
    QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Close,
    QMessageBox.StandardButton.Close,
)
if reply == QMessageBox.StandardButton.Retry:
    QTimer.singleShot(0, self._restart_scan_workers)
```

- [ ] **Step 1:** Tách chuỗi thân thiện ra `src/packrecorder/ui/camera_error_messages.py` (một hàm `mp_worker_error_dialog_text(cam_idx: int) -> str`) và test `tests/test_camera_error_messages.py`:

```python
from packrecorder.ui.camera_error_messages import mp_worker_error_dialog_text

def test_mp_worker_error_contains_cam_index():
    assert "0" in mp_worker_error_dialog_text(0)
```

- [ ] **Step 2:** Chạy `python -m pytest tests/test_camera_error_messages.py -v` — PASS.

- [ ] **Step 3:** Gắn `main_window` dùng hàm đó trong `QMessageBox` (import ở đầu file).

- [ ] **Step 4:** `python -m pytest tests/ -q` — PASS.

- [ ] **Step 5:** Commit

```bash
git add src/packrecorder/ui/main_window.py src/packrecorder/ui/camera_error_messages.py tests/test_camera_error_messages.py
git commit -m "fix(ui): camera MP worker error dialog with full restart retry"
```

---

### Task 4 (tuỳ chọn): Mã vạch **1D** cạnh QR Winson (§7.6)

**Files:**

- Add: `docs/scanner-config-codes/winson-mode-barcodes/code128-usb-com.png` (sinh bằng `scripts/generate_winson_mode_qrcodes.py` mở rộng) **hoặc** dùng `QLabel` + font không thực tế — **khuyến nghị:** sinh PNG một lần, commit file.

- Modify: `src/packrecorder/ui/settings_dialog.py` — dưới mỗi `QPixmap` QR, thêm `QLabel` ảnh Code128 nếu file tồn tại.

- [ ] **Step 1:** Chạy script (cần `qrcode[pil]` / thư viện barcode) trong môi trường dev — ghi rõ lệnh trong README của thư mục `winson-mode-barcodes` (chỉ nếu user cho phép sửa markdown — nếu không, comment trong plan đủ).

---

## Self-review

**1. Spec coverage:** §6.3 RTSP Wizard → Task 1; §4 đầy đủ → Task 2; §6.5 → Task 3; §7.6 → Task 4.

**2. Placeholder:** Không TBD; Task 3 nhánh «chỉ QMessageBox» nếu restart quá rủi ro được nêu rõ.

**3. Kiểu / tên:** `record_camera_kind` chỉ `"usb"` | `"rtsp"`; `decode_camera_index` với RTSP phải khớp logic `station_record_cam_id` / `normalize_config`.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-16-ui-ux-spec-outstanding.md`. Two execution options:

**1. Subagent-Driven (recommended)** — Dispatch a fresh subagent per task, review between tasks, fast iteration.

**2. Inline Execution** — Execute tasks in this session using executing-plans, batch execution with checkpoints.

Which approach?
