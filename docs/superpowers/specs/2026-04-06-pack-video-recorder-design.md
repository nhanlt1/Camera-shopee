# Thiết kế: Ứng dụng quay video đóng gói (Windows Desktop)

**Ngày:** 2026-04-06  
**Trạng thái:** Đã duyệt (brainstorming) — sẵn sàng cho kế hoạch triển khai.

**Chiến lược phát hành:** **MVP = một camera** (triển khai và kiểm thử trước). **Giai đoạn 2** bổ sung camera thứ hai và **PIP** trong một file.

## 1. Mục tiêu

Xây dựng ứng dụng **desktop Windows** (64-bit, Windows 10 và 11) để:

- **MVP:** Ghi video đóng gói từ **một** camera/webcam HD; **cùng thiết bị** phục vụ **quét mã** (một luồng vật lý — cách chia luồng decode vs ghi **chốt trong plan** nếu driver không cho mở kép `VideoCapture` + FFmpeg).
- **Giai đoạn 2:** Hỗ trợ **hai** camera ghi, xuất **một file** ghép **PIP cố định** (khung lớn + khung nhỏ); có thể tách **camera quét** riêng nếu cần.
- **Quét mã** (hỗ trợ **cả mã vạch 1D và QR**) để điều khiển **bắt đầu / dừng / chuyển đơn** ghi hình.
- **Cảnh báo trùng đơn:** khi chuẩn bị **mở phiên ghi mới** cho một mã đơn mà **trong thư mục ngày hiện tại** đã có video cùng đơn, app **thông báo rõ** (phi chặn) nhưng **vẫn cho phép quay** bình thường (file mới, timestamp mới — không ghi đè).
- **MVP:** Mỗi phiên ghi là **một file MP4** từ **một nguồn** (full frame HD), **không** PIP.
- **Không ghi âm** vào file video.
- **Âm thanh quầy (tùy cấu hình):** có thể bật **phát một âm thanh do app điều khiển** ngay khi **bắt đầu ghi thành công** (bổ sung cho tiếng “bíp” của **súng quét mã vạch** nếu có — tiếng súng do phần cứng/firmware; app phát thêm file âm thanh tùy chọn để xác nhận **máy tính đã vào trạng thái quay**). **Không** đưa âm này vào MP4.
- Lưu file theo **đường dẫn gốc do người dùng cấu hình**, tự tạo **một thư mục theo ngày**.
- **Tự động xóa** dữ liệu video cũ hơn **16 ngày** (an toàn, chỉ trong cấu trúc thư mục do app quản lý).
- **Tự động tắt máy** theo giờ cấu hình (mặc định **18:00**), có **bật/tắt** và **đổi giờ**; trước khi tắt: **dừng ghi** an toàn; hiển thị **đếm ngược 60 giây**; chỉ khi **hết giờ** mới giải phóng camera và gửi lệnh tắt Windows. **Hủy tắt máy:** người dùng **phải quét bất kỳ mã** (1D hoặc QR) hợp lệ trong lúc đếm ngược; khi hủy thành công, lần tự tắt **kế tiếp** được **hoãn thêm 1 giờ** kể từ lúc hủy.
- Tối đa hóa khả năng **giải phóng camera và dừng FFmpeg** khi thoát bình thường hoặc lỗi; ghi nhận giới hạn khi process bị kill cứng.

## 2. Phạm vi phiên bản đầu (MVP)

- **Ưu tiên triển khai:** **đúng một camera** — cài đặt chỉ cần chọn **một** thiết bị; không bắt buộc cấu hình camera phụ hay PIP.
- Một máy, một user vận hành tại quầy đóng gói.
- Giao diện **chỉ chế độ sáng**, phong cách **Material / Google-inspired** (PySide6 + Qt Widgets + QSS, style nền Fusion).
- Không yêu cầu đăng nhập, không đồng bộ cloud trong app (có thể lưu vào thư mục mà Google Drive / OneDrive client đồng bộ ngoài app).
- **Tắt máy hẹn giờ:** mặc định **18:00** giờ địa phương Windows; có **công tắc bật/tắt** và ô chọn **giờ:phút**; đếm ngược **60s** trước khi tắt; **hủy bằng quét mã bất kỳ**; sau hủy **hoãn +1 giờ** cho lần tắt kế tiếp.
- **Trùng đơn:** có **cơ chế báo** khi đơn đã có video trong ngày; **không chặn** ghi thêm.
- **Âm báo bắt đầu ghi:** có **bật/tắt** và (tuỳ chọn) **chọn file âm thanh** hoặc âm mặc định kèm app — xem §3.6.

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

*(Trước mỗi lần **bắt đầu file mới** cho một mã đơn — các ô trên có kết quả “Bắt đầu ghi” / “bắt đầu file mới” — áp dụng kiểm tra **trùng đơn** §3.5; không áp dụng cho hành động **chỉ dừng** ghi.)*

### 3.3 Chống nhiễu

- **Debounce** khi cùng một mã lặp trong cửa sổ thời gian ngắn (ví dụ vài trăm ms) để tránh double-fire từ một lần quét vật lý.
- Phản hồi UI: trạng thái rõ (đang ghi / chờ), đổi màu chip trạng thái; **âm “đã bắt đầu quay”** tùy cấu hình — §3.6 (không ghi âm vào video).

### 3.4 Ưu tiên khi đang đếm ngược tắt máy (60s)

- Nếu UI đang ở chế độ **hẹn tắt máy — đếm ngược** (mục 8): mọi lần **decode thành công** (bất kỳ nội dung mã nào, 1D hoặc QR) **chỉ** dùng để **hủy lệnh tắt máy** — **không** áp dụng bảng trạng thái §3.2 (không bắt đầu/dừng/chuyển đơn từ lần quét đó).
- Sau khi hủy thành công, quét trở lại hoạt động bình thường theo §3.2 (lưu ý: nếu bước 8 đã **dừng ghi** trước đếm ngược, người dùng cần quét đơn để ghi tiếp như bình thường).

### 3.5 Cảnh báo trùng đơn (không chặn ghi)

- **Định nghĩa trùng:** trong thư mục **ngày hiện tại** `{Root}/yyyy-MM-dd/` đã có **ít nhất một** file `.mp4` có dạng **`{maDon}_*.mp4`**, với `{maDon}` là phần mã đơn đã **sanitize** theo **cùng quy tắc** đặt tên §4.2. **Quy ước:** khi sanitize, **loại bỏ hoặc thay thế ký tự `_`** trong mã đơn (ví dụ thành `-`) để **một** dấu `_` duy nhất trong tên file luôn là ranh giới giữa mã và timestamp — tránh nhầm khi so khớp tiền tố.
- **Thời điểm kiểm tra:** ngay **trước** khi thực hiện bước **mở phiên ghi mới** cho mã đơn đó (sau khi đã quyết định theo §3.2 rằng sẽ có file mới). **Không** kiểm tra khi chỉ **dừng** ghi (ví dụ quét lại `A` khi đang ghi `A` để đóng file).
- **Hành vi bắt buộc:**
  - Nếu **trùng** → hiển thị **thông báo phi chặn** (không dùng hộp thoại modal bắt buộc bấm OK mới ghi — tránh làm chậm quầy): ví dụ **banner** trên cửa sổ chính, **thanh trạng thái** (`QStatusBar`) với style nổi bật ngắn, hoặc **toast** tự ẩn sau vài giây — **chốt widget trong plan**.
  - **Luôn tiếp tục** luồng ghi: tạo **file mới** `{maDon}_{yyyyMMdd-HHmmss}.mp4` như bình thường; **không ghi đè**, không hủy lệnh bắt đầu ghi.
- **Nội dung gợi ý:** *"Đơn [mã] đã có ít nhất một video hôm nay — vẫn ghi thêm."* (có thể hiển thị số file đã có — tùy chọn trong plan).
- **Hiệu năng:** kiểm tra bằng **liệt kê / glob** trong thư mục ngày (thường ít file); cache kết quả trong phiên nếu cần — **chốt trong plan** nếu thư mục lớn bất thường.

### 3.6 Âm thanh xác nhận “đã bắt đầu quay” (cấu hình)

- **Mục đích:** Giúp nhân viên **nghe thêm một tín hiệu rõ** rằng **ứng dụng đã chuyển sang đang ghi** (FFmpeg/phiên ghi đã khởi động thành công), bên cạnh tiếng phản hồi của **súng bắn mã** (nếu súng có loa/bíp riêng — app **không** điều khiển được phần đó). **Tách biệt** §1: âm này **không** mux vào file MP4.
- **Cài đặt (MVP):**
  - **Bật / tắt** toàn cục.
  - **Nguồn âm thanh:** một trong hai — (a) **âm mặc định** kèm bản cài (ví dụ file `.wav` ngắn trong thư mục `resources`), hoặc (b) **đường dẫn file do user chọn** (ưu tiên **WAV** để phát nhanh, ổn định; **MP3** nếu dùng `QMediaPlayer` hoặc backend tương đương — **chốt trong plan**).
  - **Điều khiển âm lượng** theo **mixer / thiết bị đầu ra mặc định của Windows** (app không bắt buộc có slider riêng trong MVP; có thể thêm sau).
- **Khi phát:** **một lần**, ngay sau khi xác nhận **bắt đầu ghi thành công** — tức các trường hợp dẫn tới **mở phiên ghi mới** và FFmpeg đã accept (tương đương các ô §3.2: Idle → bắt đầu ghi; hoặc Đang ghi `A` → quét `B` → **bắt đầu** file mới cho `B`). **Không** phát khi chỉ **dừng** ghi; **không** phát khi quét trong §3.4 (hủy tắt máy); **không** phát nếu bật tắt âm = tắt hoặc lỗi tải file.
- **Triển khai gợi ý:** `QSoundEffect` (WAV), hoặc `QMediaPlayer` / `QAudioOutput` (PySide6) — **chốt trong plan**; phát trên **luồng UI hoặc luồng phụ** để không block quét.

## 4. Lưu trữ và dọn dẹp 16 ngày

### 4.1 Đường dẫn

- **Root** do user chọn (ổ cục bộ, thư mục đồng bộ cloud trên máy, hoặc UNC) — miễn Windows đọc/ghi được.

### 4.2 Cấu trúc thư mục

- Mỗi ngày một thư mục con: `{Root}/yyyy-MM-dd/`.
- Tên file video: `{maDon}_{yyyyMMdd-HHmmss}.mp4` sau khi **sanitize** ký tự không hợp lệ trên Windows (`<>:"/\|?*` và ký tự điều khiển). **Bổ sung:** trong phần `{maDon}`, **không giữ ký tự `_`** (thay bằng `-` hoặc bỏ) để trùng đơn §3.5 so khớp tiền tố `"{maDon}_"` không bị sai lệch.

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
| Cấu hình | JSON hoặc `QSettings` (đường dẫn root, **MVP:** một camera; **v2:** camera phụ + PIP, vị trí/kích thước PIP, bitrate/preset, **bật tắt máy hẹn giờ**, **giờ kích hoạt** `HH:mm`; runtime **`next_shutdown_at`**; **âm báo bắt đầu ghi:** bật/tắt, đường dẫn file hoặc dùng âm mặc định kèm app) |
| Phát âm quầy | **PySide6** `QSoundEffect` / `QMediaPlayer` (hoặc tương đương) — chỉ phản hồi UI, **không** mux vào MP4 |
| Đóng gói | PyInstaller (hoặc tương đương) + ship `ffmpeg.exe` + DLL phụ thuộc decode (+ file âm mặc định nếu dùng) |

## 6. Video: MVP một nguồn và giai đoạn 2 (PIP)

- **MVP (ưu tiên):** **một** luồng video DirectShow → FFmpeg → file MP4 **full frame** (ví dụ 1920×1080 hoặc native của thiết bị — **chốt preset trong plan**). **Không** ghép PIP.
- **Giai đoạn 2:** **Hai camera ghi:** một full frame, một scale nhỏ, **overlay** cố định (ví dụ góc phải dưới); cùng một file đầu ra như spec gốc.

## 7. Kiến trúc luồng xử lý

- **Luồng UI (main):** nhận tín hiệu từ worker, cập nhật trạng thái, không block khi quét/ghi.
- **Worker quét (QThread):** lấy frame để decode (nguồn frame **chốt trong plan** cho MVP một camera: có thể từ `VideoCapture` cùng thiết bị, hoặc tách luồng nếu driver không cho mở song song với FFmpeg — tránh double-open khi không cần). Tần suất hợp lý (ví dụ 10–15 fps); emit signal sang main với chuỗi đơn đã chuẩn hóa.
- **Điều khiển ghi:** mỗi phiên ghi tương ứng **một tiến trình FFmpeg**; chuyển đơn = **dừng hợp lệ** process hiện tại rồi spawn process mới với đường dẫn output mới; sau khi xác nhận **phiên mới đã ghi thành công**, nếu cấu hình bật thì kích hoạt **§3.6**.
- **Preview (tuỳ chọn MVP):** hiển thị một camera hoặc lược đồ đơn giản; giảm FPS khi đang ghi để tiết kiệm CPU.
- **Đồng hồ tắt máy:** `QTimer` kiểm tra định kỳ so sánh **`now` với `next_shutdown_at`** (datetime địa phương). Khởi động app: tính `next_shutdown_at` = lần tới tại **`HH:mm`** trong cấu hình (ngày hôm nay nếu chưa qua, không thì ngày kế). Khi **hủy bằng quét** trong đếm ngược: `next_shutdown_at = now + 1 giờ`. Khi tính năng **bật** và `now >= next_shutdown_at` và **không** đang trong đếm ngược, kích hoạt chuỗi mục 8.

## 8. Tự động tắt máy sau giờ làm (mặc định 18:00)

### 8.1 Hành vi

- **Điều kiện:** tính năng **được bật** trong Cài đặt; app **đang chạy** tại thời điểm `now >= next_shutdown_at` (nếu app đã thoát, **sẽ không** tắt máy — không dùng Task Scheduler trong MVP trừ khi bổ sung sau).
- **Giờ mặc định trong cài đặt:** **18:00** (6 giờ chiều) địa phương; user đổi được `HH:mm`. Giá trị này dùng để **tính lại** `next_shutdown_at` khi khởi động app hoặc khi user sửa cài đặt (**chốt trong plan**).
- **Sau khi hủy bằng quét thành công:** `next_shutdown_at = thời điểm hủy thành công + 1 giờ` (cùng múi giờ máy). Có thể lặp lại nhiều lần trong ngày (mỗi lần hủy lại cộng thêm 1 giờ).
- **Sau khi máy tắt thành công:** lần mở app sau, tính lại `next_shutdown_at` từ `HH:mm` cấu hình như khởi động bình thường.

### 8.2 Chuỗi khi tới `next_shutdown_at` (đếm ngược 60s và hủy bằng quét)

1. Nếu **đang ghi:** **dừng ghi** theo luồng chuẩn (đóng FFmpeg, hoàn tất file).
2. Hiển thị **hộp thoại / màn hình đếm ngược đúng 60 giây** (cập nhật mỗi giây), nội dung rõ: *Máy sẽ tắt sau X giây — **quét bất kỳ mã vạch hoặc QR hợp lệ để hủy***. **Không** dùng nút **Hủy** bằng chuột làm luồng chính (nếu cần nút dự phòng cho admin/kẹt phần cứng, **chốt trong plan** — mặc định vận hành: **chỉ quét**).
3. **Trong suốt 60 giây:** **worker quét và camera vẫn hoạt động** (không gọi `release()` camera ở bước này). Mọi decode thành công được xử lý theo **§3.4** → **hủy tắt máy**: đóng hộp thoại đếm ngược, **không** gửi lệnh tắt Windows; cập nhật **`next_shutdown_at = now + 1 giờ`**; app tiếp tục (ghi hình đã dừng ở bước 1 — user quét đơn nếu muốn ghi tiếp).
4. **Hết 60 giây** mà **không** có quét hủy: lúc này mới gọi **`shutdown()`** nội bộ app — dừng worker quét, `release()` camera, dọn FFmpeg — rồi gửi lệnh **tắt máy Windows** (tham số thời gian / `shutdown /s` — **chốt trong plan**, tránh countdown chồng hai lớp không cần thiết).

### 8.3 Quyền và lỗi

- Một số máy / policy domain có thể **chặn** shutdown từ user: app phải **báo lỗi** rõ (không im lặng).
- Ghi chú vận hành: cần quyền tắt máy phù hợp; nếu không, dùng **chỉ dừng ghi + thoát app** làm phương án dự phòng có thể cấu hình (tùy chọn sau MVP).

## 9. Giải phóng tài nguyên và crash

- Mọi `VideoCapture` đều có đường **`release()`** trong `try`/`finally` hoặc context manager tùy bọc.
- Hàm **`shutdown()`** tập trung: dừng thread quét, `release()` camera, terminate/kill có kiểm soát **FFmpeg** child. Gọi **sau khi hết đếm ngược 60s** (mục 8.2 bước 4), khi **thoát app** bình thường, hoặc khi lỗi — **không** gọi full `release()` camera giữa chừng đếm ngược nếu vẫn cần quét để hủy (trừ khi user đóng app thủ công).
- Đăng ký **`atexit`** và xử lý ngoại lệ toàn cục nơi phù hợp để gọi `shutdown()` khi thoát bình thường hoặc lỗi chưa bắt.
- **Windows Job Object** gắn với tiến trình FFmpeg con (qua `ctypes` hoặc `pywin32`): khi process Python kết thúc, child không bị orphan giữ thiết bị.
- **Giới hạn đã thống nhất với stakeholder:** `End Task` kill cứng hoặc mất điện có thể vẫn cần thao tác vật lý (rút USB / restart camera) — tài liệu vận hành ghi rõ.

## 10. Lỗi và edge case

- **Ổ đầy / ghi UNC lỗi:** báo lỗi rõ; không giả định file luôn hoàn chỉnh nếu không stop FFmpeg bình thường.
- **Mất camera giữa chừng:** dừng ghi, thông báo, không tự restart vô hạn (có thể nút “thử lại” thủ công).
- **Quét trùng khi đang debounce:** bỏ qua log âm thầm hoặc một dòng log debug tùy cấu hình.
- **Tắt máy bị từ chối (policy / không đủ quyền):** thông báo; không giả định máy đã tắt.
- **Đếm ngược tắt máy:** quét hủy **không** làm hỏng file đã dừng ở bước 1; xác nhận **`next_shutdown_at`** cập nhật đúng **+1 giờ**. **Camera/scanner lỗi trong 60s:** không thể quét hủy — hết giờ vẫn tắt theo bước 4; nếu cần **nút dự phòng** cho sự cố phần cứng, **chốt trong plan** (ngoài luồng “chỉ quét” lý tưởng).
- **Trùng đơn:** thư mục ngày đã có `DON123_*.mp4` — quét `DON123` để **bắt đầu ghi lại** → có thông báo trùng, vẫn xuất hiện **file thứ hai** timestamp khác; quét `DON123` để **dừng** khi đang ghi → **không** bắt buộc báo trùng (hành động dừng).
- **Âm báo bắt đầu ghi:** file âm user chọn **thiếu / định dạng không phát được** → ghi log + thông báo nhẹ (hoặc im lặng có log); **không** làm fail luồng ghi; tắt bằng cài đặt nếu cần.

## 11. Kiểm thử gợi ý

- **MVP:** **một** webcam + đường dẫn local và (tuỳ) UNC / thư mục đồng bộ — xác nhận ghi ổn trước khi mở rộng.
- **Giai đoạn 2:** hai webcam, PIP, chuyển đơn dưới tải hai nguồn.
- Chuỗi: A → B → C (chuyển đơn liên tục); A → A (toggle dừng).
- Kill Python từ Task Manager: kiểm tra không còn `ffmpeg.exe` treo (Job Object).
- Ngày sang thư mục mới sau nửa đêm (hoặc theo quy ước timezone trong plan).
- Retention: thư mục giả lập >16 ngày bị xóa đúng; thư mục không đúng format không bị đụng.
- **Tắt máy hẹn giờ:** mock `next_shutdown_at` hoặc chỉnh giờ thử; UI **đếm ngược đúng 60s**; **quét bất kỳ mã** trong lúc đếm ngược → hủy, **không** gọi §3.2 cho lần quét đó; kiểm tra **`next_shutdown_at = now + 1h`**; sau hủy, quét đơn hoạt động lại bình thường; **không quét** → hết 60s → tắt máy (hoặc mô phỏng policy chặn).
- **Trùng đơn:** tạo sẵn file giả trong thư mục ngày → quét cùng mã để mở ghi mới → có **thông báo** và **hai file** (hoặc nhiều hơn) cùng tiền tố đơn; xác nhận **không** modal chặn luồng làm việc.
- **Âm báo:** bật — Idle → quét đơn → có **một** tiếng sau khi ghi chạy; Đang ghi `A` → quét `B` → có **một** tiếng khi file `B` bắt đầu; dừng ghi / đếm ngược tắt máy §3.4 → **không** phát; tắt trong cài đặt → im lặng.

## 12. Ngoài phạm vi MVP

- **Hai camera ghi + PIP trong một file** và cấu hình **camera quét tách** — thuộc **giai đoạn 2**, sau khi MVP **một camera** đã chạy ổn.
- Chế độ tối (dark theme).
- Đăng nhập đa user, phân quyền.
- Upload trực tiếp lên cloud từ app.
- Watermark, logo, hoặc burn timestamp lên video (có thể thêm sau).
- Tắt máy khi **app không chạy** (ví dụ Lịch tác vụ Windows) — có thể thêm phiên bản sau nếu cần.

## 13. Bước tiếp theo

Sau khi spec này được xác nhận lần cuối, tạo **implementation plan** chi tiết: **đường ưu tiên MVP một camera** (thứ tự task, xử lý xung đột mở camera trên Windows nếu có), sau đó mục **giai đoạn 2** (PIP hai nguồn), rủi ro FFmpeg/OpenCV, và chiến lược đóng gói.
