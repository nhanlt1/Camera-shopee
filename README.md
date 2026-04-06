# Pack Recorder

Ứng dụng desktop Windows (Python 3.11+, PySide6) quay video đóng gói, điều khiển bằng quét mã (1D/QR). Chi tiết nghiệp vụ: `docs/superpowers/specs/2026-04-06-pack-video-recorder-design.md`.

## Cài đặt dev

```powershell
cd c:\Users\nhanl\Documents\Camera-shopee
python -m venv .venv
.\.venv\Scripts\activate
pip install -e ".[dev]"
```

Cần **ffmpeg** trong `PATH` hoặc chỉ đường dẫn trong **Cài đặt**.

**pyzbar** cần DLL ZBar (ví dụ `libzbar-64.dll`) cùng thư mục exe hoặc trong `PATH`.

## Chạy

```powershell
python -m packrecorder
```

## Test

```powershell
pytest -v
```

## Đóng gói (PyInstaller)

Chỉnh đường dẫn `ffmpeg.exe` trong `packrecorder.spec`, rồi:

```powershell
pyinstaller packrecorder.spec
```

## Troubleshooting camera (spec §9.1–§9.4)

- Sau khi debug / kill process đột ngột, Windows có thể **giữ lock** camera → lần sau không mở được. Thử: tắt hết instance Python/app, **rút và cắm lại** USB webcam, hoặc Device Manager **Disable/Enable** thiết bị camera.
- **Hai webcam** trên một hub USB: dễ thiếu băng thông — nên cắm cổng USB khác nhau trên máy.
