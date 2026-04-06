# Thiết kế: Ứng dụng quay video đóng gói (Windows Desktop)

**Ngày:** 2026-04-06  
**Trạng thái:** Đã duyệt (brainstorming) — sẵn sàng cho kế hoạch triển khai.

## 1. Mục tiêu

Xây dựng ứng dụng **desktop Windows** (64-bit, Windows 10 và 11) để:

- Ghi video đóng gói hàng từ **một hoặc hai** camera/webcam chất lượng HD.
- **Quét mã** (hỗ trợ **cả mã vạch 1D và QR**) để điều khiển **bắt đầu / dừng / chuyển đơn** ghi hình.
- Xuất **một file video duy nhất** mỗi phiên ghi, ghép hai nguồn theo bố cục **PIP cố định** (khung lớn + khung nhỏ góc màn hình).
- **Không ghi âm** vào file.
- Lưu file theo **đường dẫn gốc do người dùng cấu hình**, tự tạo **một thư mục theo ngày**.
- **Tự động xóa** dữ liệu video cũ hơn **16 ngày** (an toàn, chỉ trong cấu trúc thư mục do app quản lý).
- **Tự động tắt máy** vào **18:00** (6 giờ chiều) theo giờ hệ thống, có **bật/tắt** và có thể **đổi giờ** trong cài đặt; trước khi tắt phải **dừng ghi và giải phóng tài nguyên** an toàn.
- Tối đa hóa khả năng **giải phóng camera và dừng FFmpeg** khi thoát bình thường hoặc lỗi; ghi nhận giới hạn khi process bị kill cứng.

## 2. Phạm vi phiên bản đầu (MVP)

- Một máy, một user vận hành tại quầy đóng gói.
- Giao diện **chỉ chế độ sáng**, phong cách **Material / Google-inspired** (PySide6 + Qt Widgets + QSS, style nền Fusion).
- Không yêu cầu đăng nhập, không đồng bộ cloud trong app (có thể lưu vào thư mục mà Google Drive / OneDrive client đồng bộ ngoài app).
- **Tắt máy hẹn giờ:** mặc định **18:00** giờ địa phương Windows; có **công tắc bật/tắt** và ô chọn **giờ:phút** (để sau này đổi ca làm việc mà không sửa code).

## 3. Nghiệp vụ quét và trạng thái ghi

### 3.1 Gán thiết bị (cấu hình)

- Người dùng chọn trong cài đặt:
  - **Camera ghi — khung chính** (PIP lớn).
  - **Camera ghi — khung phụ** (PIP nhỏ). Có thể tắt nếu chỉ dùng một camera ghi (khi đó chỉ một nguồn vào FFmpeg hoặc layout đơn giản hóa — xem mục 6).
  - **Camera quét** (decode mã). Có thể trùng với một trong hai camera ghi hoặc là thiết bị riêng.

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
| Mã hóa / PIP | **FFmpeg** CLI (build static đi kèm bản phân phối), hai đầu vào `dshow`, `filter_complex` **overlay**; **không** map audio (`-an`) |
| Cấu hình | JSON hoặc `QSettings` (đường dẫn root, chỉ số/tên thiết bị camera, vị trí/kích thước PIP, bitrate/preset, **bật tắt máy hẹn giờ**, **giờ kích hoạt** dạng `HH:mm` theo giờ máy) |
| Đóng gói | PyInstaller (hoặc tương đương) + ship `ffmpeg.exe` + DLL phụ thuộc decode |

## 6. Video: PIP và một nguồn

- **Hai camera ghi:** một luồng làm nền full frame, luồng kia scale nhỏ, **overlay** cố định (ví dụ góc phải dưới, offset pixel có thể là hằng số hoặc cấu hình sau MVP).
- **Một camera ghi:** MVP có thể **chỉ ghi một nguồn** full frame (không PIP) hoặc nhân đôi nguồn — **chốt trong plan** theo độ phức tạp FFmpeg; ưu tiên hành vi rõ ràng: nếu user chỉ chọn một camera ghi thì output một nguồn HD.

## 7. Kiến trúc luồng xử lý

- **Luồng UI (main):** nhận tín hiệu từ worker, cập nhật trạng thái, không block khi quét/ghi.
- **Worker quét (QThread):** lấy frame từ camera quét với tần suất hợp lý (ví dụ 10–15 fps); decode; emit signal sang main với chuỗi đơn đã chuẩn hóa.
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

- Hai webcam + một UNC + một thư mục đồng bộ (mô phỏng).
- Chuỗi: A → B → C (chuyển đơn liên tục); A → A (toggle dừng).
- Kill Python từ Task Manager: kiểm tra không còn `ffmpeg.exe` treo (Job Object).
- Ngày sang thư mục mới sau nửa đêm (hoặc theo quy ước timezone trong plan).
- Retention: thư mục giả lập >16 ngày bị xóa đúng; thư mục không đúng format không bị đụng.
- **Tắt máy 18:00:** bật tính năng, chỉnh giờ thử nghiệm (hoặc mock thời gian trong plan); xác nhận đang ghi được dừng trước shutdown; **Hủy** trong countdown không corrupt file; sau **Hủy** không bị kích hoạt lại liên tục trong cùng ngày.

## 12. Ngoài phạm vi MVP

- Chế độ tối (dark theme).
- Đăng nhập đa user, phân quyền.
- Upload trực tiếp lên cloud từ app.
- Watermark, logo, hoặc burn timestamp lên video (có thể thêm sau).
- Tắt máy khi **app không chạy** (ví dụ Lịch tác vụ Windows) — có thể thêm phiên bản sau nếu cần.

## 13. Bước tiếp theo

Sau khi spec này được xác nhận lần cuối, tạo **implementation plan** chi tiết (tasks, thứ tự, rủi ro FFmpeg/OpenCV trên Windows, và chiến lược đóng gói).
