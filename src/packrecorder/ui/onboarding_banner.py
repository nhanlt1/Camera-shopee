"""Gợi ý «Bước 1/2/3» khi onboarding chưa xong (spec §4 Phương án A)."""

from __future__ import annotations

from packrecorder.config import AppConfig


def dual_station_banner_hint(cfg: AppConfig, *, col: int) -> str | None:
    if not isinstance(cfg, AppConfig) or cfg.onboarding_complete or col >= len(
        cfg.stations
    ):
        return None
    st = cfg.stations[col]
    com_empty = not (st.scanner_serial_port or "").strip()
    if getattr(st, "scanner_input_kind", "com") == "com" and com_empty:
        return "Bước 1: Chọn máy quét COM hoặc mở Wizard."
    if com_empty and st.record_roi_norm is None:
        return "Bước 2: Kéo vùng ROI trên preview hoặc gắn máy quét."
    if cfg.first_run_setup_required:
        return "Bước 3: Hoàn tất Wizard (tên quầy, camera)."
    return None
