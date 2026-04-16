# Thiết kế: tối giản UI/UX Pack Recorder cho người mới & chế độ vận hành hằng ngày

**Ngày:** 2026-04-16  
**Trạng thái:** bản thiết kế — chờ duyệt trước khi lập kế hoạch triển khai  
**Phạm vi:** ứng dụng **Pack Recorder** (Windows, PySide6), tập trung chế độ **đa quầy** (`multi_camera_mode = stations`) vì đúng luồng «mỗi camera + máy quét + tên máy».

**Điều hướng nhanh:** mô tả **giao diện sau khi làm xong** và **chỗ bấm để mở Wizard** nằm ở **mục 11** và **mục 12** (cuối tài liệu).

---

## 1. Mục tiêu

- **Người lần đầu** mở phần mềm vẫn hiểu được «cần làm gì tiếp theo» mà không đọc tài liệu kỹ thuật.
- **Vận hành hằng ngày:** bật máy → ứng dụng tự mở (cùng Windows) → **toàn màn hình** → camera và máy quét **đã cấu hình sẵn** trong `config.json`, dùng ngay, không phải lặp lại bước cài đặt thiết bị.
- **Lần đầu kết nối:** mở app → chọn/kết nối camera → chọn máy quét cho từng quầy → đặt tên máy → bắt đầu quét mã đơn để ghi.

Các mục tiêu phi chức năng: giảm số control hiển thị đồng thời, ưu tiên ngôn ngữ tiếng Việt ngắn — một hành động một ý, tránh thuật ngữ «RTSP / VID:PID / ROI» trên màn hình chính nếu không cần thiết.

---

## 2. Giao diện hiện tại — liệt kê và mô tả (theo mã nguồn)

Nguồn tham chiếu: `docs/architecture-and-flow.md`, `src/packrecorder/ui/main_window.py`, `src/packrecorder/ui/dual_station_widget.py`, `src/packrecorder/ui/settings_dialog.py`, `src/packrecorder/app.py`.

### 2.1. Khung cửa sổ chính (`MainWindow`)

| Vùng                       | Mô tả                                                                                                                                                                                                             |
| -------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Thanh tiêu đề**          | «Pack Recorder».                                                                                                                                                                                                  |
| **Header (toolbar ngang)** | Tiêu đề «Pack Recorder», nút **Ghim** (luôn trên cùng), ô **Lưu file** (thư mục gốc video), nút **Chọn…**, nút **Làm mới thiết bị**, combo **Độ phân giải** ghi.                                                  |
| **Khu vực trung tâm**      | `QStackedWidget`: trang **hai quầy** (`DualStationWidget`) _hoặc_ nhãn hướng dẫn khi chế độ camera không phải «Đa quầy».                                                                                          |
| **Status bar**             | Chip trạng thái đơn («Chờ quét mã đơn» / tương đương khi ghi), thanh thời gian ghi (khi có), chỉ báo đồng bộ / heartbeat (tuỳ cấu hình).                                                                          |
| **Menu**                   | **Tệp** → Cài đặt, Mở thư mục nhật ký phiên; mục **Tìm kiếm video đã ghi**.                                                                                                                                       |
| **Khay hệ thống**          | Tuỳ chọn: thu vào khay, khởi động ẩn trong khay, toast. **Mục tiêu sau refactor:** trạng thái hai quầy khi thu nhỏ/ẩn cửa sổ chính ưu tiên hiển thị bằng **cửa sổ nổi Mini** (mục **6.2b**), không phụ thuộc di chuyển chuột tới icon khay nhỏ. |

### 2.2. Mỗi cột quầy (`DualStationWidget` — `QGroupBox` «Máy 1» / «Máy 2»)

Thứ tự từ trên xuống (đại khái):

1. **Banner** cảnh báo / trạng thái ghi (ẩn khi không dùng).
2. **Thời lượng ghi** (ẩn khi không ghi) **và** **hàng mã đơn** trên cùng một dòng khu vực: nhãn «Mã đơn:», ô nhập, nút **Bắt đầu ghi** (nhập tay / Enter).
3. **Preview camera** với ROI kéo thả (`RoiPreviewLabel`).
4. **Khối cấu hình thiết bị** (nhiều control):
   - **Tên máy** (nhãn + ô).
   - **Nguồn ghi:** radio **USB (webcam)** / **RTSP (IP)**.
   - **Camera ghi:** combo chỉ số camera hoặc ô URL RTSP + nút kết nối.
   - **Loại đầu vào máy quét:** combo (COM / camera decode / HID… — tùy build).
   - **COM / HID:** combo cổng, gợi ý VID:PID, hàng cấu hình HID, nhãn «máy quét đã chọn».
   - Nút **Làm mới thiết bị** (cục bộ + header cũng có).

**Chế độ xem phim (cinema):** khi cửa sổ ở trạng thái **FullScreen**, `set_cinema_mode(True)` — preview lớn hơn, **ẩn menu bar**; form cột vẫn tồn tại nhưng layout thay đổi kích thước tối thiểu preview.

### 2.3. Hộp thoại cài đặt (`SettingsDialog`)

Nhiều nhóm: **chế độ camera** (một camera / đa quầy / PIP), trang chi tiết theo chế độ, **đường dẫn ffmpeg**, **tắt máy hẹn giờ**, **âm báo**, **ghim cửa sổ**, **retention**, **backup / status.json**, **Telegram**, **khay hệ thống**, **khởi động trong khay**, v.v. Đây là nơi tập trung tùy chọn nâng cao — với người mới, mật độ thông tin cao.

### 2.4. Khởi động ứng dụng (`app.run_app`)

- Căn giữa màn hình, `show()`, cố gắng **đưa cửa sổ lên trước** (Windows).
- **Không** có bước mặc định: bật full screen hay đăng ký Windows Startup — hai việc này thuộc **cấu hình OS** hoặc **tính năng mới** (mục 5).

---

## 3. Ánh xạ yêu cầu luồng ↔ hiện trạng

### 3.1. Luồng hằng ngày (mong muốn)

1. Mở máy → app khởi động cùng Windows.
   - **Hiện tại:** cần lối tắt trong thư mục Startup hoặc Tác vụ theo lịch; ứng dụng không tự đăng ký.
2. Full screen.
   - **Hiện tại:** full screen là **trạng thái cửa sổ** người dùng có thể bật (và kích hoạt cinema); không có tùy chọn «luôn bật full screen khi mở» trong config đã xem.
3. Máy quét đã kết nối sẵn, dùng ngay.
   - **Hiện tại:** đúng **nếu** `config.json` đã lưu `scanner_serial_port` / HID / camera index; worker COM/HID tự mở lại. Người mới **chưa** có file cấu hình đầy đủ thì vẫn phải qua UI đa control.

### 3.2. Luồng lần đầu (mong muốn)

1. Mở app → kết nối camera → chọn máy quét → đặt tên → dùng.
   - **Hiện tại:** các bước **có** trong UI nhưng **không** gói thành wizard một luồng; thứ tự control không ép người dùng đi từng bước; dễ bỏ sót chế độ «Đa quầy» hoặc chọn nhầm nguồn decode.

---

## 4. Điểm khó cho người mới (vấn đề UX)

- **Mật độ cao trên một cột:** preview, mã đơn, tên máy, USB/RTSP, COM, HID, ROI cùng lúc — không có «chế độ đơn giản».
- **Thuật ngữ kỹ thuật** trên nhãn/tooltip (RTSP, VID:PID, «Camera ghi (mã nguồn)») không giải thích theo việc cần làm.
- **Chế độ camera** nằm trong Cài đặt; nếu chưa bật «Đa quầy», màn hình chỉ hiện nhãn hướng dẫn — người mới có thể không đọc hoặc không tìm thấy menu **Tệp → Cài đặt**.
- **ROI:** cần cho decode camera nhưng người dùng «chỉ muốn quét tay với máy quét» vẫn thấy vùng kéo — gây nhiễu.
- **Khởi động Windows + full screen** chưa là một «gói trải nghiệm» được định nghĩa trong sản phẩm.

---

## 5. Các hướng tiếp cận (2–3 phương án) và khuyến nghị

### Phương án A — «Progressive disclosure» trong UI hiện tại

- Giữ layout hai cột; thêm **nút «Nâng cao»** để thu gọn khối RTSP/HID/ROI.
- Thêm banner **«Bước 1/2/3»** trên mỗi cột khi phát hiện cấu hình chưa đủ.

_Ưu:_ ít thay đổi kiến trúc. _Nhược:_ vẫn nhiều thứ trên màn hình; người mới có thể mở «Nâng cao» quá sớm.

### Phương án B — Hai chế độ: «Thiết lập» và «Quầy» (khuyến nghị)

- **Chế độ Thiết lập (Setup):** wizard hoặc trình tự cố định: chọn số quầy (1–2) → cho mỗi quầy: camera → loại quét (COM / camera / HID) → chọn thiết bị → đặt tên → (tuỳ chọn) ROI chỉ khi chọn «đọc mã bằng camera» → **Hoàn tất**.
- **Chế độ Quầy (Kiosk / Daily):** chỉ preview lớn, chip trạng thái («Chờ quét» / «Đang ghi: …»), tên quầy nhỏ, **một** nút «Cài đặt nhanh» hoặc mở khóa bằng PIN / phím tắt để vào lại Setup (tránh sửa nhầm khi đang làm việc).

_Ưu:_ khớp luồng vận hành hằng ngày và lần đầu; giảm lỗi thao tác. _Nhược:_ cần state machine UI + lưu cờ ví dụ `onboarding_complete` / `kiosk_mode_default` trong config.

### Phương án C — Chỉ cải thiện copy + ẩn field

- Đổi nhãn tiếng Việt đại chúng, ẩn RTSP mặc định, defaults thông minh.

_Ưu:_ rẻ. _Nhược:_ không giải quyết triệt để overload hai cột.

**Khuyến nghị:** **Phương án B** làm xương sống; có thể tái sử dụng wizard HID hiện có (`HidPosSetupWizard`) như một bước con khi chọn HID.

---

## 6. Thiết kế đề xuất (chi tiết)

### 6.1. Cấu hình & cờ trạng thái

Bổ sung vào `AppConfig` (tên field có thể tinh chỉnh khi implement):

- `ui_mode` hoặc tách: `first_run_setup_required: bool`, `default_to_kiosk: bool`, `kiosk_fullscreen_on_start: bool`.
- **Mini-Overlay (6.2b):** `mini_overlay_enabled: bool`, `mini_overlay_click_through: bool` (tuỳ chọn), `mini_overlay_corner` (ví dụ `bottom_right`).
- `windows_startup_hint_shown: bool` (chỉ để không spam hộp thoại — **không** tự động ghi vào Registry mà không hỏi).

**Nguyên tắc:** lần đầu sau cài đặt / khi thiếu camera hoặc thiếu nguồn quét → ép vào **Setup**. Sau khi hoàn tất → lưu config và lần sau mở thẳng **Quầy**.

### 6.2. Màn hình Quầy (hằng ngày)

- **Full screen** khi `kiosk_fullscreen_on_start` bật (và có thể F11 / Esc với xác nhận thoát fullscreen để tránh thoát nhầm).
- Hiển thị tối đa:
  - Preview (cinema đã có logic tương tự).
  - Trạng thái đơn rõ ràng (màu / icon).
  - Tên máy / quầy.
  - **Không** hiện combo COM/RTSP trừ khi mở khóa Setup.
- Nút **«Mở cài đặt»** hoặc tổ hợp phím (ví dụ Ctrl+Shift+,) — có thể yêu cầu mật khẩu đơn giản nếu nghiệp vụ cần (tùy chọn, không bắt buộc MVP).

### 6.2b. Chế độ nổi Mini (Mini-Overlay) khi thu nhỏ / ẩn cửa sổ chính

**Bối cảnh kho vận:** nhân viên thường **hai tay bận** (hàng, máy quét); bắt họ **di chuột tới icon khay nhỏ** chỉ để đọc tooltip là **không thực tế**. Phương án **đã chốt** trong spec: dùng **cửa sổ nổi Mini** (Floating Overlay Widget) làm **kênh hiển thị chính** cho hai dòng Máy 1 / Máy 2 khi cửa sổ chính không còn ở foreground.

**Yêu cầu bắt buộc:** khi người dùng **thu nhỏ** (`showMinimized`), **đóng cửa sổ chính theo kiểu «ẩn xuống nền»**, hoặc **ẩn hoàn toàn** (process vẫn chạy — có thể kết hợp với `hide()` / chạy nền), phần mềm phải hiển thị **đúng hai dòng** trạng thái **hai quầy** (đa quầy), mỗi dòng: nhãn quầy + **trạng thái màu** + **mã đơn** (nếu đang ghi):

| Dòng  | Nội dung tối thiểu (ví dụ) |
| ----- | -------------------------- |
| **1** | **Máy 1:** trạng thái — ví dụ «Đang ghi ORDER123» (màu gợi ý: xanh / đỏ tùy trạng thái). |
| **2** | **Máy 2:** trạng thái — ví dụ «Chờ quét» (màu gợi ý: vàng / xám idle). |

Ví dụ định dạng thẻ (không bắt buộc emoji — có thể dùng chấm màu hoặc icon Qt):

> **Máy 1:** Đang ghi ORDER123  
> **Máy 2:** Chờ quét

**Vị trí & hình dạng:** widget **không viền** (frameless), kích thước **thẻ nhỏ** (bảng thông báo), **cố định góc dưới bên phải** màn hình chính (phía trên vùng đồng hồ taskbar), có margin an toàn để không che System Tray. **Luôn nổi trên cùng** (always on top) để nhìn thấy kể cả khi Excel / trình duyệt full screen.

**Hành vi tương tác:**

- **Double-click** vào vùng overlay → **khôi phục cửa sổ chính** (`showNormal` / `raise_` / `activateWindow`) và **ẩn overlay** (hoặc overlay chỉ ẩn khi main visible — tùy implement, nhất quán).
- **Không** bắt buộc nút X trên overlay; thoát app vẫn qua menu / khay / tắt process như hiện tại (hoặc thêm mục «Thoát» trong menu chuột phải overlay — tuỳ chọn).

**PySide6 — gợi ý cờ cửa sổ (`QWidget` hoặc `QFrame`):**

| Cờ / thuộc tính | Mục đích |
|-----------------|----------|
| `Qt.WindowType.WindowStaysOnTopHint` | Luôn trên cùng mọi ứng dụng. |
| `Qt.WindowType.FramelessWindowHint` | Không thanh tiêu đề — giống «bảng dính» trên desktop. |
| `Qt.WindowType.Tool` | Giảm nguy cơ tạo thêm nút cửa sổ rườm rà trên taskbar (kiểm tra trên Windows). |
| `Qt.WindowType.WindowTransparentForInput` (tuỳ chọn, **Cài đặt**) | **Click-through:** chuột xuyên qua overlay xuống app phía dưới (Excel, v.v.); khi bật, **double-click mở lại main** có thể cần tắt click-through hoặc dùng phím nóng — ghi rõ trong UI. |

**Quan hệ với khay hệ thống (`QSystemTrayIcon`):** **không** thay thế hoàn toàn khay nếu nghiệp vụ vẫn cần «chỉ icon + Thoát / Hiện». Khay có thể **đồng thời** tồn tại; **ưu tiên đọc trạng thái** là **Mini-Overlay**, không phải tooltip khay. Tooltip/menu khay chỉ là **dự phòng** hoặc cho máy không bật overlay.

**Taskbar:** có thể cập nhật **tiêu đề** cửa sổ chính khi minimize (một dòng tóm tắt) — **bổ sung**, không thay thế overlay.

**Cấu hình gợi ý (`AppConfig`):** `mini_overlay_enabled: bool` (mặc định bật khi refactor), `mini_overlay_click_through: bool`, `mini_overlay_corner` (ví dụ `bottom_right`).

**Phạm vi chế độ:** áp dụng cho **`multi_camera_mode = stations`**. Một quầy: dòng thứ hai «—» hoặc «(không dùng)».

**Đồng bộ:** nguồn sự thật vẫn là `OrderStateMachine` / trạng thái ghi từng `station_id` — overlay chỉ **phản chiếu**, cập nhật theo timer hoặc signal từ main (cùng luồng UI).

### 6.3. Màn hình Setup (lần đầu / khi admin sửa)

Luồng cố định khớp yêu cầu:

1. **Kết nối camera** — probe + chọn index hoặc nhập RTSP (RTSP có thể gộp vào bước «Nâng cao»).
2. **Chọn máy quét cho camera đó** — list COM thân thiện (tên thiết bị Windows nếu có), hoặc HID wizard, hoặc «Dùng camera để đọc mã» (khi đó mới hiện ROI).
3. **Đặt tên máy** — một ô, ví dụ «Quầy A».
4. **Hoàn tất** — lưu, chuyển sang Quầy.

Hỗ trợ **hai quầy** lặp lại bước 1–3 cho cột 2 hoặc «Chỉ một quầy» để ẩn cột 2.

**Khi máy quét chưa kết nối đúng (Wizard lần đầu):** nếu sau khi làm mới thiết bị vẫn **không có cổng COM** / phần mềm **không nhận diện** được máy quét (VID/PID, danh sách COM trống, v.v.), bước máy quét phải hiển thị rõ:

- Hướng dẫn ngắn: cần chế độ **USB COM** để Pack Recorder đọc qua `pyserial`.
- **Mã cấu hình khuyến nghị:** chuỗi `881001133.` (USB COM) — người dùng **quét mã này bằng chính máy quét** (đưa máy quét về đúng chế độ). Trên UI hiển thị **QR (và tùy chọn mã vạch 1D)** cùng chuỗi in được để không cần mở sách hướng dẫn giấy.
- Sau khi quét xong: nút **«Thử lại / Làm mới thiết bị»** để probe lại COM.

Tài liệu và file QR mẫu: mục **7.6** và thư mục `docs/scanner-config-codes/winson-mode-barcodes/`.

### 6.3a. Cài đặt máy quét trong phần Settings (không phải Wizard)

**Phạm vi:** màn **Cài đặt** / tab hoặc nhóm **«Máy quét / cổng COM»** — dành cho người đã vận hành, muốn **đổi chế độ** Winson mà không vào Wizard lần đầu.

- Hiển thị **ba tuỳ chọn** chế độ (**USB COM**, **USB HID**, **USB Keyboard**) dưới dạng radio button, dropdown hoặc nút chọn kèm nhãn ngắn.
- **Chỉ khi** người dùng **chọn một chế độ cụ thể**, mới hiển thị **QR code hoặc barcode** tương ứng với mã cấu hình:
  - **USB COM** — `881001133.`
  - **USB HID** — `881001131.`
  - **USB Keyboard** — `881001124.`
- Người dùng **quét đúng mã** đang hiển thị trên màn hình (hoặc có thể in tem dán nếu muốn) để chuyển máy quét sang chế độ đã chọn; sau đó **Làm mới thiết bị** và chọn cổng trong Pack Recorder.
- **Khác Wizard:** ở đây luôn có đủ **ba** lựa chọn; Wizard lần đầu chỉ **nhấn mạnh USB COM** khi phát hiện lỗi/không nhận thiết bị.

### 6.4. Khởi động cùng Windows

- Trong Setup hoặc Cài đặt nâng cao: nút **«Tạo lối tắt khởi động»** (shell:Startup) hoặc hướng dẫn 2 bước có ảnh chụp — **ưu tiên** không tự ghi Registry nếu chưa có consent rõ ràng.
- Tài liệu triển khai: đường dẫn đầy đủ tới `.exe` portable / PyInstaller.

### 6.5. Xử lý lỗi thân thiện

- Camera không mở được: một dòng «Kiểm tra USB / đang bị app khác dùng» + nút **Thử lại** + link mở Setup.
- COM mất: đã có reconnect — trên Quầy chỉ hiện chip «Mất kết nối máy quét» màu vàng/đỏ, không stack trace.

### 6.6. Kiểm thử chấp nhận (gợi ý)

- Người chưa dùng bao giờ hoàn thành Setup ≤ 3 phút với 1 camera + 1 máy quét USB-COM.
- Sau reboot mô phỏng: app mở full screen, quét mã bắt đầu ghi trong dưới 5 giây mà không cần chạm cài đặt.
- Khi minimize / ẩn cửa sổ chính: **Mini-Overlay** (6.2b) luôn hiển thị **hai dòng** Máy 1 / Máy 2 + trạng thái đơn (nhìn được **không cần chuột** tới khay); khay/tooltip chỉ dự phòng.
- Không regression: vẫn mở được `SettingsDialog` đầy đủ cho admin.

---

## 7. Tích hợp máy quét mã vạch chạy ngầm (chế độ USB COM)

Phần này cố định **nghiệp vụ triển khai** và **căn cứ phần cứng** cho máy quét Winson, đồng thời khớp với kiến trúc đã có trong repo (đọc COM bằng `pyserial` trên luồng riêng, không đi qua bộ gõ). Chi tiết kỹ thuật luồng worker: `docs/architecture-and-flow.md` mục máy quét COM.

### 7.1. Mục tiêu

- Cho phép Pack Recorder nhận mã vạch khi ứng dụng **chạy ngầm** (thu nhỏ, ẩn cửa sổ, hoặc không focus) mà **không cần** focus vào ô nhập mã trong UI.
- **Giảm sai lệch dữ liệu** do xung đột với bộ gõ tiếng Việt (Unikey, EVKey, …): khi máy quét ở chế độ giả lập bàn phím (USB-HID keyboard wedge), ký tự có thể bị biến dạng (ví dụ `SPX123W` → `SPX123ư`) nếu chuỗi đi qua IME. Chế độ **COM** đưa dữ liệu vào luồng serial, **không** qua buffer bàn phím Windows.

### 7.2. Cấu hình phần cứng (Winson WAI-5780 / WAI-5770-USB)

Mặc định nhiều máy quét dùng **USB-HID** (giả lập bàn phím). Để phù hợp kiến trúc «đọc COM trong luồng riêng», cần chuyển sang **cổng COM ảo (Virtual COM Port / VCP)**.

1. **Thiết lập trên máy quét:** quét **mã cấu hình** để bật **USB COM**. Chuỗi chính thức dùng trong dự án: **`881001133.`** (có dấu chấm cuối). Có thể dùng mã in trong _Quick Setting Manual_ Winson hoặc **QR/ảnh** trong `docs/scanner-config-codes/winson-mode-barcodes/` (xem **7.6**). Thư mục `docs/scanner-config-codes/` cũng có PDF/ảnh trang cấu hình gốc.
2. **Nhận diện trên Windows:**
   - Cắm máy quét vào PC.
   - **Device Manager** → **Ports (COM & LPT)** → ghi lại tên cổng (ví dụ `COM3`).
   - Nếu Windows không tạo cổng COM: cài **Winson Virtual COM Driver** từ trang chủ hãng (hoặc gói driver kèm thiết bị), rồi cắm lại thiết bị.
3. **Thông số nối tiếp mặc định (theo tài liệu hãng):** **115200** baud, **8** data bits, **không parity**, **1** stop bit (**8N1**). Trong Pack Recorder, baud và cổng lưu theo từng quầy trong `StationConfig` (đồng bộ với UI combo COM).

### 7.3. Triển khai trong codebase (đối chiếu, không trùng lặp module)

- **Thư viện:** `pyserial` (khai báo trong `pyproject.toml` / cài `pip install pyserial`).
- **Module thực tế:** `src/packrecorder/serial_scan_worker.py` — `SerialScanWorker` (`QThread`): vòng lặp đọc `readline()` trên cổng đã mở, debounce, reconnect khi lỗi; phát tín hiệu về `MainWindow` qua **`QueuedConnection`** để xử lý mã đơn trên luồng UI.
- **Mã giả** dưới đây chỉ minh hoạ **mô hình** (thread + signal); khi sửa code, ưu tiên mở rộng `SerialScanWorker` thay vì nhân đôi lớp tương tự:

```python
# Pseudo-code — mô hình tham khảo (logic thật: serial_scan_worker.SerialScanWorker)
import serial
from PySide6.QtCore import QThread, Signal

class BarcodeScannerWorker(QThread):
    barcode_received = Signal(str)

    def __init__(self, port_name="COM3", baudrate=115200):
        super().__init__()
        self.port_name = port_name
        self.baudrate = baudrate  # Winson VCP: thường 115200
        self.running = True

    def run(self):
        with serial.Serial(self.port_name, baudrate=self.baudrate, timeout=1) as ser:
            while self.running:
                if ser.in_waiting > 0:
                    line = ser.readline().decode("utf-8", errors="replace").strip()
                    if line:
                        self.barcode_received.emit(line)
```

### 7.4. Ưu điểm kiến trúc (COM so với wedge bàn phím)

| Khía cạnh            | Ý nghĩa vận hành                                                                                                                                                                                                         |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| **IME / Unikey**     | Dữ liệu không đi qua pipeline bàn phím → hạn chế lỗi ký tự khi nhân viên đang gõ tiếng Việt ở app khác.                                                                                                                  |
| **Non-blocking UX**  | Nhân viên có thể dùng chuột, trình duyệt, cửa sổ khác; worker COM vẫn nhận dòng mã. Pack Recorder map mã vào `OrderStateMachine` và ghi video **không phụ thuộc** focus ô «Mã đơn» (đã cấu hình đúng nguồn quầy).        |
| **Chạy ngầm / overlay** | COM không yêu cầu cửa sổ đang foreground. Khi ẩn / minimize, trạng thái hai quầy hiển thị bằng **Mini-Overlay** (mục **6.2b**); khay vẫn có thể dùng cho Thoát / tùy chọn nhưng **không** là kênh đọc trạng thái chính. |

**Lưu ý:** «Kích hoạt WriterProcess» trong mô tả nghiệp vụ tương ứng với luồng ghi FFmpeg / `encode_writer_worker` trong tài liệu kiến trúc — không đổi tên class trong spec này; khi implement chỉ cần đảm bảo `_on_serial_decoded` → state machine → start/stop ghi vẫn nhất quán.

### 7.5. Liên kết với thiết kế UI (mục 6)

- Wizard **Setup** (mục 6.3) nên có bước **«Máy quét COM (khuyến nghị — tránh lỗi IME)»** với hướng dẫn ngắn: quét mã **USB COM** (`881001133.`) trên Winson → chọn `COMx` → baud **115200**. Khi không nhận thiết bị: hiển thị QR/chuỗi (6.3).
- **Settings — cài đặt máy quét** (mục 6.3a): hiển thị đủ ba mã chế độ (COM / HID / Keyboard) dưới dạng QR để đổi chế độ bất kỳ lúc nào.
- Màn **Quầy** (mục 6.2) không cần ô nhập focus để nhận mã từ COM; vẫn nên hiển thị chip trạng thái khi COM lỗi (mục 6.5).
- **Minimize / ẩn hoàn toàn:** bắt buộc phản chiếu Máy 1 + Máy 2 và đơn hiện tại (mục **6.2b**).

### 7.6. Bảng mã cấu hình chế độ Winson (chuỗi quét + QR)

Các giá trị sau là **chuỗi đầy đủ** cần gửi vào máy quét (kể cả ký tự `.` cuối). Dùng để: in tem, hiển thị trong UI (Settings + Wizard khi lỗi), hoặc tạo lại file ảnh bằng `scripts/generate_winson_mode_qrcodes.py`.

| Chế độ           | Chuỗi        | Ghi chú                                                           |
| ---------------- | ------------ | ----------------------------------------------------------------- |
| **USB COM**      | `881001133.` | Khớp Pack Recorder (`pyserial`); khuyến nghị vận hành.            |
| **USB HID**      | `881001131.` | Tùy chọn nếu dùng luồng HID trong app.                            |
| **USB Keyboard** | `881001124.` | Wedge bàn phím — dễ xung đột IME; không khuyến nghị cho COM-only. |

**QR (PNG) trong repo** — nội dung mã hoá trùng chuỗi cột «Chuỗi»:

| File         | Đường dẫn                                                                                                                                   |
| ------------ | ------------------------------------------------------------------------------------------------------------------------------------------- |
| USB COM      | [`docs/scanner-config-codes/winson-mode-barcodes/qr-usb-com.png`](../../scanner-config-codes/winson-mode-barcodes/qr-usb-com.png)           |
| USB HID      | [`docs/scanner-config-codes/winson-mode-barcodes/qr-usb-hid.png`](../../scanner-config-codes/winson-mode-barcodes/qr-usb-hid.png)           |
| USB Keyboard | [`docs/scanner-config-codes/winson-mode-barcodes/qr-usb-keyboard.png`](../../scanner-config-codes/winson-mode-barcodes/qr-usb-keyboard.png) |

Xem thêm bảng và hướng dẫn in: [`docs/scanner-config-codes/winson-mode-barcodes/README.md`](../../scanner-config-codes/winson-mode-barcodes/README.md).

**Mã vạch 1D:** có thể tạo từ cùng chuỗi (Code128/Code39 tùy hỗ trợ máy quét) bằng phần mềm nhãn; UI ứng dụng có thể render sau (không bắt buộc trùng định dạng file với QR).

**Preview ảnh QR (cùng nội dung với file PNG trong repo):**

|                                    USB COM                                    |                                    USB HID                                    |                                      USB Keyboard                                       |
| :---------------------------------------------------------------------------: | :---------------------------------------------------------------------------: | :-------------------------------------------------------------------------------------: |
| ![QR USB COM](../../scanner-config-codes/winson-mode-barcodes/qr-usb-com.png) | ![QR USB HID](../../scanner-config-codes/winson-mode-barcodes/qr-usb-hid.png) | ![QR USB Keyboard](../../scanner-config-codes/winson-mode-barcodes/qr-usb-keyboard.png) |
|                                 `881001133.`                                  |                                 `881001131.`                                  |                                      `881001124.`                                       |

---

## 8. Phạm vi ngoài (YAGNI cho phiên bản thiết kế này)

- Đổi kiến trúc pipeline multiprocessing.
- Đa ngôn ngữ đầy đủ (chỉ Việt/Anh tối thiểu nếu cần).
- Quản lý user / đăng nhập cloud.

---

## 9. Phụ lục — file mã và tài liệu liên quan

| File                                              | Vai trò                                                        |
| ------------------------------------------------- | -------------------------------------------------------------- |
| `src/packrecorder/ui/main_window.py`              | Khung cửa sổ, menu, header, status, full screen ↔ cinema       |
| `src/packrecorder/ui/dual_station_widget.py`      | Hai cột, preview, form thiết bị                                |
| `src/packrecorder/ui/settings_dialog.py`          | Cài đặt nâng cao                                               |
| `src/packrecorder/ui/hid_pos_setup_wizard.py`     | Wizard HID có thể tái sử dụng                                  |
| `src/packrecorder/config.py`                      | `AppConfig`, `StationConfig`, đường dẫn JSON                   |
| `src/packrecorder/app.py`                         | Khởi động Qt, stylesheet                                       |
| `docs/architecture-and-flow.md`                   | Kiến trúc tổng quan                                            |
| `src/packrecorder/serial_scan_worker.py`          | Worker COM (`pyserial`, `QThread`), queue giới hạn, reconnect  |
| `docs/scanner-config-codes/`                      | Mã cấu hình Winson (PDF/ảnh gốc)                               |
| `docs/scanner-config-codes/winson-mode-barcodes/` | QR PNG + README cho `881001133.` / `881001131.` / `881001124.` |
| `scripts/generate_winson_mode_qrcodes.py`         | Tạo lại file QR (cần `pip install qrcode[pil]`)                |

---

## 10. Ghi chú tự rà soát (spec)

- **Giả định:** một máy trạm điển hình dùng 1–2 quầy; không mô tả chi tiết chế độ PIP/single trong màn Quầy (có thể vẫn dùng UI hiện tại cho các chế độ đó).
- **Quyết định UX (kho vận):** trạng thái khi thu nhỏ/ẩn cửa sổ chính ưu tiên **cửa sổ nổi Mini** (6.2b), không phụ thuộc tooltip/icon khay; khay vẫn có thể tồn tại cho lệnh phụ.
- **Rủi ro:** full screen + Esc cần thiết kế cẩn thận để không khóa người dùng; nên giữ taskbar hoặc phím tắt thoát rõ ràng.
- **Bước tiếp theo sau khi duyệt spec:** lập kế hoạch triển khai theo skill `writing-plans` (chia task: config flags, widget Quầy, wizard Setup + nhánh lỗi máy quét (QR `881001133.`), màn Settings máy quét (ba QR), **`MiniStatusOverlay` / cửa sổ nổi Mini** (6.2b: PySide6 flags, vị trí, double-click restore, tuỳ chọn click-through), tích hợp khay dự phòng, startup shortcut, QA).

---

## 11. Giao diện mục tiêu sau chỉnh sửa (mô tả cho người dùng cuối)

Phần này **tổng hợp** trạng thái UI sau khi triển khai các mục 5–7 (không trùng lặp từng bullet kỹ thuật). **Chưa có trong bản build hiện tại** cho đến khi code theo spec.

### 11.1. Hai chế độ màn hình chính

| Chế độ                 | Người dùng thấy gì                                                                                                                                                                                                                                                                                                                                                                                                                    |
| ---------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **Quầy (hằng ngày)**   | Màn hình **tối giản:** preview camera mỗi quầy (lớn nếu bật full screen / cinema), **chip hoặc nhãn trạng thái** rõ «Chờ quét» / «Đang ghi: …» cho **Máy 1** và **Máy 2**, tên quầy. **Không** còn khối combo USB/RTSP/COM/HID/ROI trên mặt Quầy — chỉ khi mở **Thiết lập** (Wizard hoặc Cài đặt nâng cao). Một nút kiểu **«Thiết lập máy & quầy»** (Wizard) tách biệt với **Tệp → Cài đặt** (Settings đầy đủ) — chi tiết **mục 12**. |
| **Thiết lập (Wizard)** | Trình tự **từng bước** (màn hình từng trang hoặc sidebar): camera → máy quét → tên quầy → hoàn tất; có nhánh **QR `881001133.`** khi không nhận COM (**6.3**).                                                                                                                                                                                                                                                                        |

### 11.2. Thanh menu và header (mục tiêu)

- **Menu Tệp:** giữ **Cài đặt** (hộp thoại đầy đủ cho admin); thêm mục **«Trình hướng dẫn thiết lập quầy…»** (mở Wizard) — chi tiết **mục 12.1**.
- **Thanh trên cùng ở chế độ Quầy:** có thể chỉ còn: **Ghim** (tuỳ chọn), **Đường dẫn lưu video** (hoặc rút gọn), **Độ phân giải ghi** (hoặc ẩn sau «Nâng cao»), nút **«Thiết lập máy & quầy»** (Wizard). **Làm mới thiết bị** có thể nằm trong Cài đặt hoặc Wizard để giảm nhiễu trên Quầy.

### 11.3. Cài đặt nâng cao (`SettingsDialog`)

- Vẫn là nơi **ffmpeg**, **khay**, **retention**, **backup**, **Telegram**, v.v.
- Thêm (hoặc gom) nhóm **«Máy quét / mã Winson»** với **ba QR** đổi chế độ (**6.3a**) — **không** thay thế Wizard; dành cho người đã biết, cần đổi USB COM / HID / Keyboard nhanh.

### 11.4. Mini-Overlay, khay và taskbar

- **Chính:** khi cửa sổ chính không hiện, **cửa sổ nổi Mini** góc dưới phải luôn hiện **hai dòng** Máy 1 / Máy 2 + trạng thái (**6.2b**) — nhìn được ngay, không cần tìm icon khay.
- **Khay:** giữ cho Thoát / Hiện / tuỳ chọn; **không** coi tooltip khay là cách đọc trạng thái chính.
- **Taskbar:** tiêu đề rút gọn (tuỳ chọn) khi minimize — bổ sung, không thay overlay.

### 11.5. So với giao diện hiện tại (mục 2)

- **Trước:** hai cột `DualStationWidget` luôn hiện form cấu hình thiết bị dài cùng preview.
- **Sau:** trên **Quầy**, ưu tiên **hình + trạng thái**; form chi tiết chuyển sang **Wizard** hoặc **Cài đặt**.

---

## 12. Wizard thiết lập — các bước và người dùng mở bằng cách nào

Wizard là **một hộp thoại / stack các bước** (QWizard hoặc tương đương), nội dung logic theo **6.3**. Dưới đây là **điểm vào** cố định trong thiết kế (implement phải có ít nhất các lối (1)–(3); (4)–(5) tuỳ chọn).

### 12.1. Bảng: click / thao tác nào mở Wizard?

| #                     | Kích hoạt                                                                              | Người dùng làm gì (vị trí trên màn hình)                                                                                                                                            |
| --------------------- | -------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **1 — Tự động**       | Lần đầu mở app sau cài, hoặc khi `first_run_setup_required` / chưa hoàn tất onboarding | **Không cần click:** Wizard **tự hiện** (modal phủ cửa sổ chính hoặc thay thế tạm nội dung trung tâm).                                                                              |
| **2 — Menu**          | Mở lại Wizard bất kỳ lúc nào                                                           | Thanh menu → **Tệp** → **«Trình hướng dẫn thiết lập quầy…»** (hoặc tên tương đương đã thống nhất trong bản dịch).                                                                   |
| **3 — Nút trên Quầy** | Từ chế độ vận hành hằng ngày                                                           | Trên **header** hoặc **góc màn hình Quầy**, bấm nút **«Thiết lập máy & quầy»** (hoặc **«Thiết lập»** / **«Cài đặt quầy»** — tránh trùng với **Tệp → Cài đặt** mở `SettingsDialog`). |
| **4 — Từ Cài đặt**    | Admin muốn chạy lại Wizard mà không nhớ menu Tệp                                       | Trong **Cài đặt** (`SettingsDialog`): liên kết **«Chạy trình hướng dẫn thiết lập…»** (đặt cuối hộp thoại hoặc tab «Chung»).                                                         |
| **5 — Khay / nền**    | App đang ẩn hoặc chỉ còn overlay                                                   | **Chuột phải** icon khay → **«Thiết lập quầy…»** *hoặc* **double-click** vào **Mini-Overlay** để mở lại cửa sổ chính rồi dùng menu **Tệp** / nút Quầy để vào Wizard (**6.2b**). |

**Phân biệt:** Wizard (**mục 12**) ≠ **Cài đặt** đầy đủ (**SettingsDialog**): Wizard = luồng từng bước cho người mới; Settings = tất cả tùy chọn + nhóm QR Winson (**6.3a**).

### 12.2. Các bước trong Wizard (thứ tự)

1. **Chào / số quầy:** chọn **một** hoặc **hai** quầy (hoặc bỏ qua nếu luôn hai quầy cố định).
2. **Máy 1 — Camera:** chọn chỉ số webcam hoặc RTSP (nâng cao); xem trước tối thiểu hoặc «Thử kết nối».
3. **Máy 1 — Máy quét:** chọn COM / HID / đọc mã bằng camera; **nếu không thấy COM** → hiện QR **`881001133.`** + nút làm mới (**6.3**).
4. **Máy 1 — Tên quầy:** ô tên (ví dụ «Quầy A»).
5. **Máy 2** — lặp bước 2–4 nếu bật hai quầy (hoặc một màn gộp tùy implement).
6. **Hoàn tất:** lưu `config.json`, đặt cờ đã onboarding, chuyển sang **Quầy** (và bật full screen nếu cấu hình).

Các bước có thể gộp trên một số màn hình miễn giữ **thứ tự nhận thức:** camera trước, máy quét sau, tên cuối.

### 12.3. Ghi chú triển khai

- Tên menu / nút trong **12.1** có thể tinh chỉnh copywriting nhưng **phải** giữ hai lối rõ: **Tệp → Trình hướng dẫn…** và **nút trên Quầy**.
- Nếu sản phẩm dùng **PIN** để vào Cài đặt (**6.2**), có thể áp dụng tương tự cho nút mở Wizard trên Quầy (tuỳ nghiệp vụ).

---

_Tài liệu này mô tả thiết kế UX/UI; không chứa thay đổi mã. Chỉnh sửa theo phản hồi người dùng trước khi code._
