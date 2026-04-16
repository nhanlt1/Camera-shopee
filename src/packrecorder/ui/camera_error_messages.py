"""Chuỗi giao diện cho lỗi camera / worker (tách khỏi main_window để test nhẹ)."""


def mp_worker_error_dialog_text(cam_idx: int) -> str:
    return (
        f"Camera {cam_idx}: thử lại mở thiết bị hoặc vào Tệp → «Thiết lập máy & quầy» "
        "để đổi camera/URL RTSP.\n"
        "Bấm «Thử lại» để khởi động lại toàn bộ luồng camera (giống watchdog)."
    )
