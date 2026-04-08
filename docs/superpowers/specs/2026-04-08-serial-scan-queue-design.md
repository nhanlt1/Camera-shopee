# Thiết kế: Hàng đợi giới hạn cho máy quét COM (cách 1)

**Ngày:** 2026-04-08  
**Trạng thái:** Đã triển khai trong code (`serial_scan_worker.py`, `tests/test_serial_scan_queue.py`)

## Bối cảnh

- Người dùng muốn áp dụng ý tưởng “đọc serial tách luồng / không nghẽn giao diện” tương tự hướng dẫn phổ biến (Readline / từng dòng), **không** thêm WebSocket hay tiến trình riêng chỉ để phát mã ra mạng.
- Đã chọn **cách 1:** giữ mô hình Qt (`QThread` / worker), thêm **hàng đợi có giới hạn** giữa phần đọc cổng và phần báo cho giao diện.

## Hiện trạng trong code

- `SerialScanWorker` (`src/packrecorder/serial_scan_worker.py`): một `QThread`, mở `pyserial`, vòng lặp `readline()`, debounce trùng nhanh, rồi `line_decoded.emit(station_id, text)`.
- `MainWindow` nối signal với `QueuedConnection` tới `_on_serial_decoded` (`src/packrecorder/ui/main_window.py`).
- Hành vi nghiệp vụ (chuẩn hóa mã, đồng bộ UI, ghi hình) **giữ nguyên**; thay đổi chỉ nằm ở lớp đọc COM / chuyển sự kiện.

## Mục tiêu

1. **Giới hạn bộ nhớ / số sự kiện chờ** khi giao diện hoặc luồng chính bận (tránh chuỗi `emit` vô hạn trong worker).
2. **Giữ một đường đi rõ:** đọc cổng → (tùy chọn debounce) → hàng đợi → báo UI.
3. **Không** đổi yêu cầu người dùng: vẫn không WebSocket; không bắt buộc tách file Python chạy riêng.

## Thiết kế

### Hàng đợi

- Dùng `queue.Queue(maxsize=N)` với **N cố định** (ví dụ 32 hoặc 64 — chọn một giá trị trong lúc implement, có hằng số tên rõ).
- Phần tử trong queue: tối thiểu `(station_id: str, text: str)` tương đương dữ liệu hiện emit.

### Khi queue đầy

- **Chính sách:** bỏ **bản cũ nhất** rồi mới `put` bản mới (FIFO, ưu tiên mã mới nhất khi quá tải).
- **Ghi nhật ký:** log **giới hạn tần suất** (ví dụ tối đa một dòng mỗi vài giây khi đang mất mã do đầy queue) để không spam `session_log`.

### Luồng thực thi (producer / consumer)

Để hàng đợi thực sự tách “đọc blocking” và “báo UI”:

- **Producer:** luồng chuyên đọc COM (khuyến nghị: `threading.Thread` daemon trong phạm vi worker, hoặc giữ một vòng lặp rõ ràng chỉ `readline` + `put`). Debounce **có thể** giữ ngay sau khi có dòng hợp lệ **trước khi** `put` để không nhồi queue bằng các bản trùng mà worker hiện tại đã lọc.
- **Consumer:** phần còn lại của `SerialScanWorker` (vẫn chạy trong ngữ cảnh Qt worker phù hợp) **chỉ** `get` (có timeout ngắn để có thể kiểm tra `stop`) và `line_decoded.emit(...)`.

**Lưu ý:** Mở/đóng cổng serial **một chỗ** (thread sở hữu cổng), tránh hai luồng cùng `read`/`close` không đồng bộ.

### Dừng và lỗi

- Cờ dừng hiện có (`stop_worker` / `_running`): signal tới producer để thoát vòng lặp, `join` thread đọc (timeout hợp lý), đóng serial, consumer thoát sạch.
- Lỗi mở COM hoặc `SerialException` khi đọc: giữ hành vi tương đương hiện tại (`failed.emit`), không để thread treo.

### Kiểm thử

- Unit test: mock thời gian / queue — kiểm tra khi queue đầy thì **số phần tử không vượt maxsize** và **policy drop-oldest** (có thể inject queue giả).
- Không bắt buộc test tích hợp phần cứng thật.

## Phạm vi không làm trong spec này

- WebSocket, HTTP broadcast, tiến trình Python độc lập gửi sang server.
- Đổi giao diện hay luồng camera / FFmpeg.
- Thay `QueuedConnection` bằng cơ chế khác trừ khi phát sinh từ review implement.

## Tiêu chí xong

- [x] `SerialScanWorker` có `queue.Queue(maxsize=SERIAL_SCAN_QUEUE_MAX)` + bỏ bản cũ khi đầy + log WARNING có giới hạn tần suất.
- [x] Dừng: `stop_worker()` đóng cổng serial (mở khóa `readline`) + `join` luồng đọc.
- [x] Debounce giữ như trước khi `put` vào queue; hành vi quét bình thường không đổi.
