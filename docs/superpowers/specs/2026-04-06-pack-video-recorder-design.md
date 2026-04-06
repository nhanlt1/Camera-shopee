# Thiết kế: Ứng dụng quay video đóng gói (Windows Desktop)

**Ngày:** 2026-04-06  
**Trạng thái:** Đã duyệt (brainstorming) — sẵn sàng cho kế hoạch triển khai.

**Chiến lược phát hành:** **MVP = một camera** (triển khai và kiểm thử trước). **Giai đoạn 2** bổ sung camera thứ hai và **PIP** trong một file.

## 1. Mục tiêu

Xây dựng ứng dụng **desktop Windows** (64-bit, Windows 10 và 11) để:

- **MVP:** Ghi video đóng gói từ **một** camera/webcam HD; **cùng thiết bị** phục vụ **quét mã** (một luồng vật lý — cách chia luồng decode vs ghi **chốt trong plan** nếu driver không cho mở kép `VideoCapture` + FFmpeg).
- **Giai đoạn 2:** Hỗ trợ **hai** camera ghi, xuất **một file** ghép **PIP cố định** (khung lớn + khung nhỏ); có thể tách **camera quét** riêng nếu cần.
- **Quét mã** (hỗ trợ **cả mã vạch 1D và QR**) để điều khiển **bắt đầu / dừng / chuyển đơn** ghi hình.
- **MVP:** Mỗi phiên ghi là **một file MP4** từ **một nguồn** (full frame HD), **không** PIP.
- **Không ghi âm** vào file.
- Lưu file theo **đường dẫn gốc do người dùng cấu hình**, tự tạo **một thư mục theo ngày**.
- **Tự động xóa** dữ liệu video cũ hơn **16 ngày** (an toàn, chỉ trong cấu trúc thư mục do app quản lý).
- **Tự động tắt máy** vào **18:00** (6 giờ chiều) theo giờ hệ thống, có **bật/tắt** và có thể **đổi giờ** trong cài đặt; trước khi tắt phải **dừng ghi và giải phóng tài nguyên** an toàn.
- Tối đa hóa khả năng **giải phóng camera và dừng FFmpeg** khi thoát bình thường hoặc lỗi; ghi nhận giới hạn khi process bị kill cứng.

## 2. Phạm vi phiên bản đầu (MVP)

- **Ưu tiên triển khai:** **đúng một camera** — cài đặt chỉ cần chọn **một** thiết bị; không bắt buộc cấu hình camera phụ hay PIP.
- Một máy, một user vận hành tại quầy đóng gói.
- Giao diện **chỉ chế độ sáng**, phong cách **Material / Google-inspired** (PySide6 + Qt Widgets + QSS, style nền Fusion).
- Không yêu cầu đăng nhập, không đồng bộ cloud trong app (có thể lưu vào thư mục mà Google Drive / OneDrive client đồng bộ ngoài app).
- **Tắt máy hẹn giờ:** mặc định **18:00** giờ địa phương Windows; có **công tắc bật/tắt** và ô chọn **giờ:phút** (để sau này đổi ca làm việc mà không sửa code).

## 3. Nghiệp vụ quét và trạng thái ghi

### 3.1 Gán thiết bị (cấu hình)

- **MVP — một camera:**
  - Một mục chọn **Camera** (nguồn duy nhất cho cả **ghi** và **quét** trên cùng thiết bị).
- **Giai đoạn 2** (sau khi MVP ổn định):
  - **Camera ghi — khung chính** (PIP lớn).
  - **Camera ghi — khung phụ** (PIP nhỏ).
  - **Camera quét** (decode mã): có thể trùng một trong hai camera ghi hoặc riêng.

### 3.2 Máy trạng thái theo mã đơn

Giả định chuỗi decode được chuẩn hóa (trim, có thể quy tắc chữ hoa/thường thống nhất trong cấu hình).

| Trạng thái | Hành động quét | Kết quả |
|------------|----------------|---------|
| Idle | Quét đơn `A` | Bắt đầu ghi; file mới gắn với `A`. |
| Đang ghi `A` | Quét lại `A` | Dừng ghi; đóng file hiện tại. |
| Đang ghi `A` | Quét `B` (`B` ≠ `A`) | Dừng file của `A`; **ngay sau đó** bắt đầu file mới cho `B`. |

### 3.3 Chống nhiễu

- **Debounce** khi cùng một mã lặp trong cửa sổ thời gian ngắn (ví dụ vài trăm ms) để tránh double-fire từ một lần quét vật lý.
- Phản hồi UI: trạng thái rõ (đang ghi / chờ), có thể **beep hệ thống** hoặc đổi màu chip trạng thái (không ghi âm vào video).

## 4. Lưu trữ và dọn dẹp 16 ngày

### 4.1 Đường dẫn

- **Root** do user chọn (ổ cục bộ, thư mục đồng bộ cloud trên máy, hoặc UNC) — miễn Windows đọc/ghi được.

### 4.2 Cấu trúc thư mục

- Mỗi ngày một thư mục con: `{Root}/yyyy-MM-dd/`.
- Tên file video: `{maDon}_{yyyyMMdd-HHmmss}.mp4` sau khi **sanitize** ký tự không hợp lệ trên Windows (`<>:"/\|?*` và ký tự điều khiển).

### 4.3 Retention

- Xóa các thư mục con của `Root` có tên đúng định dạng `yyyy-MM-dd` và có **tuổi > 16 ngày** (so với “ngày trong tên thư mục” hoặc mtime — **chốt kỹ thuật trong plan triển khai**: ưu tiên so theo ngày trong tên để tránh lệch timezone mtime).
- Chỉ xóa trong phạm vi cấu trúc này; **không** quét xóa file tùy tiện ngoài pattern.
- Chạy **khi khởi động app** và **định kỳ** (ví dụ mỗi 6 giờ) trên luồng nền để không đơ UI.

## 5. Công nghệ và thành phần

| Thành phần | Lựa chọn |
|-------------|----------|
| Ngôn ngữ | Python 3.11+ (64-bit) |
| UI | **PySide6**, Qt Widgets, style **Fusion**, **QSS** (Material/Google light) |
| Camera / frame | **OpenCV** (`VideoCapture`), backend DirectShow trên Windows khi phù hợp |
| Decode 1D + QR | Thư viện decode ổn định trên Windows (ví dụ **pyzbar** + runtime **ZBar**, hoặc phương án tương đương) — chốt trong plan nếu có ràng buộc license/binary |
| Mã hóa / video | **FFmpeg** CLI (build static đi kèm bản phân phối): **MVP** — **một** đầu vào `dshow`; **giai đoạn 2** — hai đầu vào + `filter_complex` **overlay** (PIP); **không** map audio (`-an`) |
| Cấu hình | JSON hoặc `QSettings` (đường dẫn root, **MVP:** một camera; **v2:** camera phụ + PIP, vị trí/kích thước PIP, bitrate/preset, **bật tắt máy hẹn giờ**, **giờ kích hoạt** `HH:mm`) |
| Đóng gói | PyInstaller (hoặc tương đương) + ship `ffmpeg.exe` + DLL phụ thuộc decode |

## 6. Video: MVP một nguồn và giai đoạn 2 (PIP)

- **MVP (ưu tiên):** **một** luồng video DirectShow → FFmpeg → file MP4 **full frame** (ví dụ 1920×1080 hoặc native của thiết bị — **chốt preset trong plan**). **Không** ghép PIP.
- **Giai đoạn 2:** **Hai camera ghi:** một full frame, một scale nhỏ, **overlay** cố định (ví dụ góc phải dưới); cùng một file đầu ra như spec gốc.

## 7. Kiến trúc luồng xử lý

- **Luồng UI (main):** nhận tín hiệu từ worker, cập nhật trạng thái, không block khi quét/ghi.
- **Worker quét (QThread):** lấy frame để decode (nguồn frame **chốt trong plan** cho MVP một camera: có thể từ `VideoCapture` cùng thiết bị, hoặc tách luồng nếu driver không cho mở song song với FFmpeg — tránh double-open khi không cần). Tần suất hợp lý (ví dụ 10–15 fps); emit signal sang main với chuỗi đơn đã chuẩn hóa.
- **Điều khiển ghi:** mỗi phiên ghi tương ứng **một tiến trình FFmpeg**; chuyển đơn = **dừng hợp lệ** process hiện tại rồi spawn process mới với đường dẫn output mới.
- **Preview (tuỳ chọn MVP):** hiển thị một camera hoặc lược đồ đơn giản; giảm FPS khi đang ghi để tiết kiệm CPU.
- **Đồng hồ tắt máy:** `QTimer` kiểm tra định kỳ (ví dụ mỗi 30–60 giây) so sánh **giờ hệ thống địa phương** với giờ cấu hình; khi đạt ngưỡng và tính năng **bật**, kích hoạt chuỗi tắt máy (mục 8).

## 8. Tự động tắt máy sau giờ làm (mặc định 18:00)

### 8.1 Hành vi

- **Điều kiện:** tính năng **được bật** trong Cài đặt; app **đang chạy** tại thời điểm đến giờ (nếu app đã thoát trước đó, **sẽ không** tắt máy — không dùng Windows Task Scheduler trong MVP trừ khi bổ sung sau).
- **Giờ kích hoạt:** mặc định **18:00** (6 giờ chiều) theo **múi giờ / giờ địa phương** của Windows; người dùng có thể đổi sang giờ khác (`HH:mm`).
- **Một lần mỗi ngày:** sau khi đã thực hiện chuỗi tắt máy (hoặc sau khi người dùng **Hủy** trong hộp thoại đếm ngược — xem dưới), **không** kích hoạt lại cho đến **ngày lịch tiếp theo** (tránh bật lại liên tục nếu người dùng hủy shutdown hoặc shutdown thất bại).

### 8.2 Trước khi gửi lệnh tắt Windows

1. Nếu **đang ghi:** **dừng ghi** theo luồng chuẩn (đóng FFmpeg, hoàn tất file).
2. Gọi **`shutdown()`** nội bộ của app: dừng worker quét, `release()` camera, dọn process con.
3. Hiển thị **hộp thoại đếm ngược** (ví dụ **60 giây**) với nội dung rõ: *Máy sẽ tắt sau X giây*; nút **Hủy** để abort shutdown (app tiếp tục chạy; đánh dấu đã xử lý “lần trong ngày” để không lặp lại ngay).
4. Gọi lệnh **tắt máy Windows** (ví dụ `shutdown /s /t <giây>` với `t` nhỏ nếu đã chờ trong app, hoặc `t 0` sau khi đã countdown trong UI — **chốt trong plan** để tránh hai lớp countdown chồng nhau).

### 8.3 Quyền và lỗi

- Một số máy / policy domain có thể **chặn** shutdown từ user: app phải **báo lỗi** rõ (không im lặng).
- Ghi chú vận hành: cần quyền tắt máy phù hợp; nếu không, dùng **chỉ dừng ghi + thoát app** làm phương án dự phòng có thể cấu hình (tùy chọn sau MVP).

## 9. Giải phóng tài nguyên và crash

- Mọi `VideoCapture` đều có đường **`release()`** trong `try`/`finally` hoặc context manager tùy bọc.
- Hàm **`shutdown()`** tập trung: dừng thread quét, `release()` camera, terminate/kill có kiểm soát **FFmpeg** child.
- Đăng ký **`atexit`** và xử lý ngoại lệ toàn cục nơi phù hợp để gọi `shutdown()` khi thoát bình thường hoặc lỗi chưa bắt.
- **Windows Job Object** gắn với tiến trình FFmpeg con (qua `ctypes` hoặc `pywin32`): khi process Python kết thúc, child không bị orphan giữ thiết bị.
- **Giới hạn đã thống nhất với stakeholder:** `End Task` kill cứng hoặc mất điện có thể vẫn cần thao tác vật lý (rút USB / restart camera) — tài liệu vận hành ghi rõ.

## 10. Lỗi và edge case

- **Ổ đầy / ghi UNC lỗi:** báo lỗi rõ; không giả định file luôn hoàn chỉnh nếu không stop FFmpeg bình thường.
- **Mất camera giữa chừng:** dừng ghi, thông báo, không tự restart vô hạn (có thể nút “thử lại” thủ công).
- **Quét trùng khi đang debounce:** bỏ qua log âm thầm hoặc một dòng log debug tùy cấu hình.
- **Tắt máy bị từ chối (policy / không đủ quyền):** thông báo; không giả định máy đã tắt.

## 11. Kiểm thử gợi ý

- **MVP:** **một** webcam + đường dẫn local và (tuỳ) UNC / thư mục đồng bộ — xác nhận ghi ổn trước khi mở rộng.
- **Giai đoạn 2:** hai webcam, PIP, chuyển đơn dưới tải hai nguồn.
- Chuỗi: A → B → C (chuyển đơn liên tục); A → A (toggle dừng).
- Kill Python từ Task Manager: kiểm tra không còn `ffmpeg.exe` treo (Job Object).
- Ngày sang thư mục mới sau nửa đêm (hoặc theo quy ước timezone trong plan).
- Retention: thư mục giả lập >16 ngày bị xóa đúng; thư mục không đúng format không bị đụng.
- **Tắt máy 18:00:** bật tính năng, chỉnh giờ thử nghiệm (hoặc mock thời gian trong plan); xác nhận đang ghi được dừng trước shutdown; **Hủy** trong countdown không corrupt file; sau **Hủy** không bị kích hoạt lại liên tục trong cùng ngày.

## 12. Ngoài phạm vi MVP

- **Hai camera ghi + PIP trong một file** và cấu hình **camera quét tách** — thuộc **giai đoạn 2**, sau khi MVP **một camera** đã chạy ổn.
- Chế độ tối (dark theme).
- Đăng nhập đa user, phân quyền.
- Upload trực tiếp lên cloud từ app.
- Watermark, logo, hoặc burn timestamp lên video (có thể thêm sau).
- Tắt máy khi **app không chạy** (ví dụ Lịch tác vụ Windows) — có thể thêm phiên bản sau nếu cần.

## 13. Bước tiếp theo

Sau khi spec này được xác nhận lần cuối, tạo **implementation plan** chi tiết: **đường ưu tiên MVP một camera** (thứ tự task, xử lý xung đột mở camera trên Windows nếu có), sau đó mục **giai đoạn 2** (PIP hai nguồn), rủi ro FFmpeg/OpenCV, và chiến lược đóng gói.
