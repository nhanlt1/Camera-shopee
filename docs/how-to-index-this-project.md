# Cách index / điều hướng dự án Pack Recorder

Tài liệu mô tả **cách lập bản đồ tinh thần** và **thứ tự đọc mã** khi làm việc với repo này (cho dev hoặc agent). Không thay thế spec nghiệp vụ; nó bổ sung bằng cách chỉ **điểm neo** và **mẫu tìm kiếm**.

---

## 1. Đọc gì trước (thứ tự gợi ý)

1. **`README.md`** — cài đặt, chạy, test, build PyInstaller, troubleshooting camera ngắn gọn.
2. **`docs/architecture-and-flow.md`** — kiến trúc hiện tại, bảng module theo vai trò, luồng khởi động và camera (đây là “bản đồ chính”).
3. **`pyproject.toml`** — tên gói `packrecorder`, Python `>=3.11`, dependencies, `pythonpath = ["src"]` cho pytest, entry `packrecorder = packrecorder.__main__:main`.
4. **Spec/plan trong `docs/superpowers/`** — khi cần bối cảnh thiết kế hoặc quyết định lịch sử (tên file có ngày).

Sau đó mới đi sâu vào `src/packrecorder/` theo **luồng nghiệp vụ** bạn đang sửa (UI, camera, quét mã, ghi file, v.v.).

---

## 2. Bố cục repo (mức cao)

| Vị trí | Nội dung |
|--------|----------|
| `src/packrecorder/` | Toàn bộ ứng dụng Python (package chính). |
| `src/packrecorder/ui/` | PySide6: `main_window`, `dual_station_widget`, dialog, QSS. |
| `src/packrecorder/ipc/` | Multiprocessing: pipeline camera, capture/scanner workers, ring buffer, health, backoff. |
| `tests/` | Pytest; tên file thường `test_<module>.py` tương ứng module nguồn. |
| `scripts/` | Build portable, GitHub push helper. |
| `resources/` | `ffmpeg`, âm thanh (README trong thư mục). |
| `*.spec` | PyInstaller (`packrecorder.spec`, `packrecorder_console.spec`). |
| `run_packrecorder*.bat` | Shortcut chạy trên Windows. |

**Entry điển hình:** `python -m packrecorder` → `packrecorder/__main__.py` → import `app` và chạy GUI.

---

## 3. Trục theo chủ đề (để “gắn nhãn” file nhanh)

- **Khởi động & vòng đời app:** `app.py`, `__main__.py`, `session_log.py`, `process_priority.py`.
- **Cấu hình lưu/đọc:** `config.py` (`AppConfig`, `StationConfig`, JSON).
- **Điều phối UI & trạng thái đơn:** `ui/main_window.py`, `order_state.py`, `order_input.py`.
- **Hai quầy / camera kép:** `ui/dual_station_widget.py`, `pip_composite.py` (PIP), `record_roi.py`, `roi_preview_label.py`.
- **Camera (OpenCV / RTSP):** `opencv_video.py`, `camera_probe.py`, `camera_probe_thread.py`.
- **Pipeline đa tiến trình:** `ipc/pipeline.py`, `ipc/capture_worker.py`, `ipc/scanner_worker.py`, `ipc/frame_ring.py`, `ipc/encode_writer_worker.py`, `ipc/subprocess_recorder.py`.
- **Độ tin cậy capture:** `ipc/capture_backoff.py`, `ipc/health.py`, `shm_cleanup.py`.
- **Quét mã:** `scan_worker.py` (in-process khi tắt MP), `serial_scan_worker.py`, `hid_pos_scan_worker.py`, `hid_report_parse.py`, `hid_scanner_discovery.py`, `barcode_decode.py`.
- **Ghi video / FFmpeg:** `ffmpeg_pipe_recorder.py`, `ffmpeg_locate.py`, `ffmpeg_encoders.py`.
- **Lưu trữ & tìm kiếm:** `recording_index.py`, `storage_resolver.py`, `ui/recording_search_dialog.py`, `retention.py`, `duplicate.py`.
- **Đồng bộ / trạng thái ngoài:** `sync_worker.py`, `status_publish.py`, `heartbeat_consumer.py`, `telegram_notify.py`.
- **Windows / tiến trình:** `subprocess_win.py`, `windows_job.py`, `shutdown_scheduler.py`.

Khi không chắc module nào: mở **`docs/architecture-and-flow.md`** phần bảng module — đã map sẵn file ↔ vai trò.

---

## 4. Cách “index” bằng tìm kiếm (grep / codebase search)

- **Luồng gọi từ UI:** từ `MainWindow` hoặc `DualStationWidget`, trace method/private slot liên quan tính năng.
- **Biến môi trường / cờ:** tìm `os.environ`, `getenv`, hoặc chuỗi `PACKRECORDER_` — nhiều hành vi (ví dụ tắt multiprocessing) được điều khiển qua env.
- **Hành vi theo test:** mở `tests/test_<tên>.py` tương ứng; test thường là ví dụ nhỏ nhất của contract API.
- **IPC / shared memory:** tìm `packrecorder_pr_`, `SharedMemory`, `frame_ring`, `latest_seq` trong `ipc/`.
- **Cấu hình JSON:** tìm field trong `config.py` rồi grep tên field trong `ui/` và `main_window`.

Semantic search (câu hỏi kiểu “ai tạo pipeline camera?”) hữu ích sau khi đã có vài từ khóa từ bảng trên.

---

## 5. Kiểm chứng nhanh sau khi đọc/sửa

```powershell
cd c:\Users\nhanl\Documents\Camera-shopee
.\.venv\Scripts\activate
pytest -q
```

(`pythonpath` đã cấu hình trong `pyproject.toml`; chạy từ root repo.)

---

## 6. Cập nhật tài liệu

Khi refactor lớn (đổi tên module, tách pipeline, đổi entry), nên cập nhật **`docs/architecture-and-flow.md`** và (nếu cần) mục bảng trong file này để lần “index” sau không lệch thực tế.
