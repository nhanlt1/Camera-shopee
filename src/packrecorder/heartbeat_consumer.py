from __future__ import annotations


def office_heartbeat_state(
    age_seconds: float,
    *,
    fresh_s: int = 120,
    stale_s: int = 300,
) -> tuple[str, str, bool]:
    """
    age_seconds: chênh lệch (now - last_heartbeat), giây, >= 0.
    Trả về (light, status_bar_message, show_search_delay_warning).
    """
    if age_seconds <= fresh_s:
        return ("green", "Hệ thống đang đồng bộ", False)
    if age_seconds <= stale_s:
        return (
            "yellow",
            "Có thể trễ — kiểm tra máy đóng gói hoặc Drive",
            False,
        )
    return (
        "red",
        "CẢNH BÁO: Mất kết nối với máy đóng gói (có thể do lỗi Drive hoặc mất mạng)",
        True,
    )
