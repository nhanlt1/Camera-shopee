# Thiết kế: tối giản UI/UX Pack Recorder cho người mới & chế độ vận hành hằng ngày

**Ngày:** 2026-04-16  
**Trạng thái:** bản thiết kế — chờ duyệt trước khi lập kế hoạch triển khai  
**Phạm vi:** ứng dụng **Pack Recorder** (Windows, PySide6), tập trung chế độ **đa quầy** (`multi_camera_mode = stations`) vì đúng luồng «mỗi camera + máy quét + tên máy».

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

| Vùng | Mô tả |
|------|--------|
| **Thanh tiêu đề** | «Pack Recorder». |
| **Header (toolbar ngang)** | Tiêu đề «Pack Recorder», nút **Ghim** (luôn trên cùng), ô **Lưu file** (thư mục gốc video), nút **Chọn…**, nút **Làm mới thiết bị**, combo **Độ phân giải** ghi. |
| **Khu vực trung tâm** | `QStackedWidget`: trang **hai quầy** (`DualStationWidget`) *hoặc* nhãn hướng dẫn khi chế độ camera không phải «Đa quầy». |
| **Status bar** | Chip trạng thái đơn («Chờ quét mã đơn» / tương đương khi ghi), thanh thời gian ghi (khi có), chỉ báo đồng bộ / heartbeat (tuỳ cấu hình). |
| **Menu** | **Tệp** → Cài đặt, Mở thư mục nhật ký phiên; mục **Tìm kiếm video đã ghi**. |
| **Khay hệ thống** | Tuỳ chọn: thu vào khay, khởi động ẩn trong khay (sau ~2,8s), toast khi có đơn (tuỳ chọn). |

### 2.2. Mỗi cột quầy (`DualStationWidget` — `QGroupBox` «Máy 1» / «Máy 2»)

Thứ tự từ trên xuống (đại khái):

1. **Banner** cảnh báo / trạng thái ghi (ẩn khi không dùng).
2. **Thời lượng ghi** (ẩn khi không ghi).
3. **Hàng mã đơn:** nhãn «Mã đơn:», ô nhập, nút **Bắt đầu ghi** (nhập tay / Enter).
4. **Preview camera** với ROI kéo thả (`RoiPreviewLabel`).
5. **Khối cấu hình thiết bị** (nhiều control):
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

*Ưu:* ít thay đổi kiến trúc. *Nhược:* vẫn nhiều thứ trên màn hình; người mới có thể mở «Nâng cao» quá sớm.

### Phương án B — Hai chế độ: «Thiết lập» và «Quầy» (khuyến nghị)

- **Chế độ Thiết lập (Setup):** wizard hoặc trình tự cố định: chọn số quầy (1–2) → cho mỗi quầy: camera → loại quét (COM / camera / HID) → chọn thiết bị → đặt tên → (tuỳ chọn) ROI chỉ khi chọn «đọc mã bằng camera» → **Hoàn tất**.
- **Chế độ Quầy (Kiosk / Daily):** chỉ preview lớn, chip trạng thái («Chờ quét» / «Đang ghi: …»), tên quầy nhỏ, **một** nút «Cài đặt nhanh» hoặc mở khóa bằng PIN / phím tắt để vào lại Setup (tránh sửa nhầm khi đang làm việc).

*Ưu:* khớp luồng vận hành hằng ngày và lần đầu; giảm lỗi thao tác. *Nhược:* cần state machine UI + lưu cờ ví dụ `onboarding_complete` / `kiosk_mode_default` trong config.

### Phương án C — Chỉ cải thiện copy + ẩn field

- Đổi nhãn tiếng Việt đại chúng, ẩn RTSP mặc định, defaults thông minh.

*Ưu:* rẻ. *Nhược:* không giải quyết triệt để overload hai cột.

**Khuyến nghị:** **Phương án B** làm xương sống; có thể tái sử dụng wizard HID hiện có (`HidPosSetupWizard`) như một bước con khi chọn HID.

---

## 6. Thiết kế đề xuất (chi tiết)

### 6.1. Cấu hình & cờ trạng thái

Bổ sung vào `AppConfig` (tên field có thể tinh chỉnh khi implement):

- `ui_mode` hoặc tách: `first_run_setup_required: bool`, `default_to_kiosk: bool`, `kiosk_fullscreen_on_start: bool`.
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

### 6.3. Màn hình Setup (lần đầu / khi admin sửa)

Luồng cố định khớp yêu cầu:

1. **Kết nối camera** — probe + chọn index hoặc nhập RTSP (RTSP có thể gộp vào bước «Nâng cao»).
2. **Chọn máy quét cho camera đó** — list COM thân thiện (tên thiết bị Windows nếu có), hoặc HID wizard, hoặc «Dùng camera để đọc mã» (khi đó mới hiện ROI).
3. **Đặt tên máy** — một ô, ví dụ «Quầy A».
4. **Hoàn tất** — lưu, chuyển sang Quầy.

Hỗ trợ **hai quầy** lặp lại bước 1–3 cho cột 2 hoặc «Chỉ một quầy» để ẩn cột 2.

### 6.4. Khởi động cùng Windows

- Trong Setup hoặc Cài đặt nâng cao: nút **«Tạo lối tắt khởi động»** (shell:Startup) hoặc hướng dẫn 2 bước có ảnh chụp — **ưu tiên** không tự ghi Registry nếu chưa có consent rõ ràng.
- Tài liệu triển khai: đường dẫn đầy đủ tới `.exe` portable / PyInstaller.

### 6.5. Xử lý lỗi thân thiện

- Camera không mở được: một dòng «Kiểm tra USB / đang bị app khác dùng» + nút **Thử lại** + link mở Setup.
- COM mất: đã có reconnect — trên Quầy chỉ hiện chip «Mất kết nối máy quét» màu vàng/đỏ, không stack trace.

### 6.6. Kiểm thử chấp nhận (gợi ý)

- Người chưa dùng bao giờ hoàn thành Setup ≤ 3 phút với 1 camera + 1 máy quét USB-COM.
- Sau reboot mô phỏng: app mở full screen, quét mã bắt đầu ghi trong dưới 5 giây mà không cần chạm cài đặt.
- Không regression: vẫn mở được `SettingsDialog` đầy đủ cho admin.

---

## 7. Tích hợp máy quét mã vạch chạy ngầm (chế độ USB COM)

Phần này cố định **nghiệp vụ triển khai** và **căn cứ phần cứng** cho máy quét Winson, đồng thời khớp với kiến trúc đã có trong repo (đọc COM bằng `pyserial` trên luồng riêng, không đi qua bộ gõ). Chi tiết kỹ thuật luồng worker: `docs/architecture-and-flow.md` mục máy quét COM.

### 7.1. Mục tiêu

- Cho phép Pack Recorder nhận mã vạch khi ứng dụng **chạy ngầm** (thu nhỏ, ẩn cửa sổ, hoặc không focus) mà **không cần** focus vào ô nhập mã trong UI.
- **Giảm sai lệch dữ liệu** do xung đột với bộ gõ tiếng Việt (Unikey, EVKey, …): khi máy quét ở chế độ giả lập bàn phím (USB-HID keyboard wedge), ký tự có thể bị biến dạng (ví dụ `SPX123W` → `SPX123ư`) nếu chuỗi đi qua IME. Chế độ **COM** đưa dữ liệu vào luồng serial, **không** qua buffer bàn phím Windows.

### 7.2. Cấu hình phần cứng (Winson WAI-5780 / WAI-5770-USB)

Mặc định nhiều máy quét dùng **USB-HID** (giả lập bàn phím). Để phù hợp kiến trúc «đọc COM trong luồng riêng», cần chuyển sang **cổng COM ảo (Virtual COM Port / VCP)**.

1. **Thiết lập trên máy quét:** quét mã cấu hình có nhãn **`USB COM`** trong tài liệu *Quick Setting Manual* của Winson (thường nằm **Trang 1** — bảng mã cấu hình). Trong repo có tài liệu tham chiếu: `docs/scanner-config-codes/` (PDF/ảnh trang cấu hình).
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

| Khía cạnh | Ý nghĩa vận hành |
|-----------|-------------------|
| **IME / Unikey** | Dữ liệu không đi qua pipeline bàn phím → hạn chế lỗi ký tự khi nhân viên đang gõ tiếng Việt ở app khác. |
| **Non-blocking UX** | Nhân viên có thể dùng chuột, trình duyệt, cửa sổ khác; worker COM vẫn nhận dòng mã. Pack Recorder map mã vào `OrderStateMachine` và ghi video **không phụ thuộc** focus ô «Mã đơn» (đã cấu hình đúng nguồn quầy). |
| **Chạy ngầm / khay** | Tương thích với tùy chọn **thu vào khay** (`minimize_to_tray`, `start_in_tray`): COM không yêu cầu cửa sổ đang foreground. |

**Lưu ý:** «Kích hoạt WriterProcess» trong mô tả nghiệp vụ tương ứng với luồng ghi FFmpeg / `encode_writer_worker` trong tài liệu kiến trúc — không đổi tên class trong spec này; khi implement chỉ cần đảm bảo `_on_serial_decoded` → state machine → start/stop ghi vẫn nhất quán.

### 7.5. Liên kết với thiết kế UI (mục 6)

- Wizard **Setup** (mục 6.3) nên có bước **«Máy quét COM (khuyến nghị — tránh lỗi IME)»** với hướng dẫn ngắn: quét mã **USB COM** trên Winson → chọn `COMx` → baud **115200**.
- Màn **Quầy** (mục 6.2) không cần ô nhập focus để nhận mã từ COM; vẫn nên hiển thị chip trạng thái khi COM lỗi (mục 6.5).

---

## 8. Phạm vi ngoài (YAGNI cho phiên bản thiết kế này)

- Đổi kiến trúc pipeline multiprocessing.
- Đa ngôn ngữ đầy đủ (chỉ Việt/Anh tối thiểu nếu cần).
- Quản lý user / đăng nhập cloud.

---

## 9. Phụ lục — file mã và tài liệu liên quan

| File | Vai trò |
|------|---------|
| `src/packrecorder/ui/main_window.py` | Khung cửa sổ, menu, header, status, full screen ↔ cinema |
| `src/packrecorder/ui/dual_station_widget.py` | Hai cột, preview, form thiết bị |
| `src/packrecorder/ui/settings_dialog.py` | Cài đặt nâng cao |
| `src/packrecorder/ui/hid_pos_setup_wizard.py` | Wizard HID có thể tái sử dụng |
| `src/packrecorder/config.py` | `AppConfig`, `StationConfig`, đường dẫn JSON |
| `src/packrecorder/app.py` | Khởi động Qt, stylesheet |
| `docs/architecture-and-flow.md` | Kiến trúc tổng quan |
| `src/packrecorder/serial_scan_worker.py` | Worker COM (`pyserial`, `QThread`), queue giới hạn, reconnect |
| `docs/scanner-config-codes/` | Mã cấu hình Winson (USB COM, v.v.) — tham chiếu triển khai |

---

## 10. Ghi chú tự rà soát (spec)

- **Giả định:** một máy trạm điển hình dùng 1–2 quầy; không mô tả chi tiết chế độ PIP/single trong màn Quầy (có thể vẫn dùng UI hiện tại cho các chế độ đó).
- **Rủi ro:** full screen + Esc cần thiết kế cẩn thận để không khóa người dùng; nên giữ taskbar hoặc phím tắt thoát rõ ràng.
- **Bước tiếp theo sau khi duyệt spec:** lập kế hoạch triển khai theo skill `writing-plans` (chia task: config flags, widget Quầy, wizard Setup, startup shortcut, tài liệu Winson COM trong onboarding, QA).

---

*Tài liệu này mô tả thiết kế UX/UI; không chứa thay đổi mã. Chỉnh sửa theo phản hồi người dùng trước khi code.*
