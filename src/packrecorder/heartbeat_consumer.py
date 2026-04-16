from __future__ import annotations


def _format_disconnect_minutes(age_seconds: float) -> str:
    mins = max(0, int(round(float(age_seconds) / 60.0)))
    return f"{mins} phút"


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
            f"Có thể trễ — mất kết nối khoảng {_format_disconnect_minutes(age_seconds)}; kiểm tra máy đóng gói hoặc Drive",
            False,
        )
    return (
        "red",
        f"CẢNH BÁO: Mất kết nối với máy đóng gói khoảng {_format_disconnect_minutes(age_seconds)} (có thể do lỗi Drive hoặc mất mạng)",
        True,
    )
