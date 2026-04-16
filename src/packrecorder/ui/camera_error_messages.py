"""Chuỗi giao diện cho lỗi camera / worker (tách khỏi main_window để test nhẹ)."""


def mp_worker_error_dialog_text(cam_idx: int) -> str:
    return (
        f"Camera {cam_idx}: thử lại mở thiết bị hoặc đổi camera / URL RTSP trong "
        "«Thiết lập máy & quầy».\n"
        "Chi tiết kỹ thuật nằm trong nhật ký phiên."
    )


def mp_worker_error_dialog_buttons() -> tuple[str, str, str]:
    return ("Thử lại", "Thiết lập máy & quầy", "Đóng")
