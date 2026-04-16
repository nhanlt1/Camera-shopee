# Mã cấu hình chế độ Winson (quét vào máy quét)

Các chuỗi dưới đây là **mã cấu hình** trong tài liệu Quick Setting (Winson): quét bằng máy quét để đổi chế độ USB. Chuỗi **phải gồm dấu chấm cuối** (`.`) đúng như bảng.

| Chế độ | Chuỗi quét | File QR (PNG) |
|--------|------------|----------------|
| **USB COM** (Virtual COM — khuyến nghị cho Pack Recorder) | `881001133.` | [qr-usb-com.png](qr-usb-com.png) |
| **USB HID** | `881001131.` | [qr-usb-hid.png](qr-usb-hid.png) |
| **USB Keyboard** (wedge bàn phím) | `881001124.` | [qr-usb-keyboard.png](qr-usb-keyboard.png) |

## Tạo lại file PNG (tùy chọn)

```bash
pip install qrcode[pil]
python scripts/generate_winson_mode_qrcodes.py
```

## Ghi chú

- **QR** mã hoá đúng từng byte của chuỗi (kể cả `.` cuối), phù hợp in tem dán cạnh máy trạm.
- Máy quét **1D** (Code128/Code39…) cần in tem cùng nội dung từ phần mềm nhãn — không dùng chung file PNG QR nếu thiết bị chỉ đọc 1D.
