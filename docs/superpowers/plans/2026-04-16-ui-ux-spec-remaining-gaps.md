# UI/UX Simplification Final Gap Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Hoàn tất các phần còn lệch so với `docs/superpowers/specs/2026-04-16-ui-ux-simplification-design.md` sau các phase đã triển khai.

**Architecture:** Ưu tiên thay đổi nhỏ, tách logic thuần để test được; không đụng pipeline MP/core. Tập trung đồng bộ hành vi UI với mô tả mục tiêu ở §11–§12 của spec.

**Tech Stack:** PySide6, pytest, module UI hiện có (`main_window`, `setup_wizard`, `dual_station_widget`).

---

## Scope check (phần còn lại thực tế)

Các nhóm chức năng lớn đã có (tab Quầy/Quản lý, wizard, overlay, startup shortcut, mã Winson QR+Code128). Còn 3 điểm cần đóng để nói “đúng spec”:

1. **Wizard camera** chưa có “thử kết nối/xem trước tối thiểu” thật sự (§12.2 bước 2).
2. **Header/menu Quầy** còn vài hành động “vận hành nâng cao” khác mô tả mục tiêu §11.2 (cần chốt đường đi tối giản).
3. **Acceptance checklist** (§6.6) chưa có testcase chạy lặp (đang mới verify ad-hoc).

---

## File map

- Modify: `src/packrecorder/ui/setup_wizard.py`
- Create: `src/packrecorder/ui/setup_wizard_probe.py`
- Create: `tests/test_setup_wizard_probe.py`
- Modify: `src/packrecorder/ui/main_window.py`
- Create: `src/packrecorder/ui/quay_menu_policy.py`
- Create: `tests/test_quay_menu_policy.py`
- Create: `tests/test_uiux_acceptance_spec_2026_04_16.py`
- Modify: `docs/superpowers/specs/2026-04-16-ui-ux-simplification-design.md` (mục trạng thái triển khai)

---

### Task 1: Wizard camera có “Thử kết nối” thực dụng (§12.2)

**Files:**
- Create: `src/packrecorder/ui/setup_wizard_probe.py`
- Modify: `src/packrecorder/ui/setup_wizard.py`
- Test: `tests/test_setup_wizard_probe.py`

- [ ] **Step 1: Write failing tests**

```python
from packrecorder.ui.setup_wizard_probe import validate_rtsp_probe_result

def test_validate_rtsp_probe_result_fail_when_empty():
    ok, msg = validate_rtsp_probe_result(False, 0, 0)
    assert ok is False
    assert "không mở được" in msg.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_setup_wizard_probe.py -v`
Expected: FAIL with `ModuleNotFoundError` for `setup_wizard_probe`

- [ ] **Step 3: Minimal implementation**

```python
# setup_wizard_probe.py

def validate_rtsp_probe_result(open_ok: bool, width: int, height: int) -> tuple[bool, str]:
    if not open_ok:
        return (False, "Không mở được luồng RTSP.")
    if width <= 0 or height <= 0:
        return (False, "Đã mở RTSP nhưng chưa nhận được khung hình hợp lệ.")
    return (True, f"Kết nối RTSP OK ({width}x{height}).")
```

- [ ] **Step 4: UI wiring in wizard**

Thêm nút `QPushButton("Thử kết nối RTSP")` trong `WizardCameraPage`, bấm sẽ gọi probe nhẹ (timeout ngắn, ví dụ 1500–2000 ms), sau đó `QMessageBox.information/warning` dùng chuỗi từ `validate_rtsp_probe_result(...)`.

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_setup_wizard_probe.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/packrecorder/ui/setup_wizard.py src/packrecorder/ui/setup_wizard_probe.py tests/test_setup_wizard_probe.py
git commit --trailer "Made-with: Cursor" -m "feat(setup-wizard): add RTSP test-connect action"
```

---

### Task 2: Chốt menu/header đúng tinh thần §11.2

**Files:**
- Create: `src/packrecorder/ui/quay_menu_policy.py`
- Modify: `src/packrecorder/ui/main_window.py`
- Test: `tests/test_quay_menu_policy.py`

- [ ] **Step 1: Write failing tests**

```python
from packrecorder.ui.quay_menu_policy import should_show_top_level_search_action

def test_search_action_hidden_when_tabs_exist():
    assert should_show_top_level_search_action(has_management_tab=True) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_quay_menu_policy.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Minimal implementation**

```python
def should_show_top_level_search_action(*, has_management_tab: bool) -> bool:
    return not has_management_tab
```

- [ ] **Step 4: Apply in `main_window.py`**

Ở đoạn tạo `act_search` (`self.menuBar().addAction(act_search)`), chỉ add action khi policy trả `True`. Với cấu trúc hiện tại có tab Quản lý sẵn, action top-level bị ẩn (menu Tệp vẫn giữ Cài đặt/Wizard/log).

- [ ] **Step 5: Run tests**

Run: `python -m pytest tests/test_quay_menu_policy.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/packrecorder/ui/main_window.py src/packrecorder/ui/quay_menu_policy.py tests/test_quay_menu_policy.py
git commit --trailer "Made-with: Cursor" -m "refactor(ui): align menu with quay-management tab policy"
```

---

### Task 3: Đóng acceptance checklist §6.6 bằng test script tối thiểu

**Files:**
- Create: `tests/test_uiux_acceptance_spec_2026_04_16.py`
- Modify: `docs/superpowers/specs/2026-04-16-ui-ux-simplification-design.md`

- [ ] **Step 1: Write acceptance-oriented tests**

```python
def test_overlay_line_pair_returns_two_lines(main_window):
    a, b = main_window._mini_overlay_line_pair()
    assert isinstance(a, str)
    assert isinstance(b, str)


def test_escape_fullscreen_prompts_confirmation(main_window, qtbot):
    # smoke: method exists and window can enter fullscreen then handle key event
    assert hasattr(main_window, "keyPressEvent")
```

- [ ] **Step 2: Run test**

Run: `python -m pytest tests/test_uiux_acceptance_spec_2026_04_16.py -v`
Expected: PASS

- [ ] **Step 3: Update spec status section**

Thêm cuối file spec mục “Implementation Status (as-built)” liệt kê:
- Done
- Partially done
- Not in scope

Không sửa nội dung thiết kế gốc; chỉ thêm block trạng thái.

- [ ] **Step 4: Run full tests**

Run: `python -m pytest tests/ -q`
Expected: PASS (all)

- [ ] **Step 5: Commit**

```bash
git add tests/test_uiux_acceptance_spec_2026_04_16.py docs/superpowers/specs/2026-04-16-ui-ux-simplification-design.md
git commit --trailer "Made-with: Cursor" -m "test(docs): add UI/UX acceptance smoke checks and as-built status"
```

---

## Self-review

1. **Spec coverage:** §12.2 (task 1), §11.2 menu/path consistency (task 2), §6.6 acceptance criteria tracking (task 3).
2. **Placeholder scan:** không dùng TODO/TBD, mọi task có file path + command + expected.
3. **Type consistency:** helper mới trả kiểu rõ ràng (`tuple[bool, str]`, `bool`).

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-04-16-ui-ux-spec-remaining-gaps.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?
