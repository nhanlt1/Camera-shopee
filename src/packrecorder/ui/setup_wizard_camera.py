"""Logic thuần cho trang Camera của Setup Wizard (USB vs RTSP)."""

from __future__ import annotations

from dataclasses import replace

from packrecorder.config import STATION_RTSP_LOGICAL_ID_BASE, StationConfig


def apply_wizard_camera_station(
    st: StationConfig,
    col: int,
    *,
    use_usb: bool,
    usb_index: int,
    rtsp_url: str,
) -> StationConfig:
    if use_usb:
        return replace(
            st,
            record_camera_index=int(usb_index),
            decode_camera_index=int(usb_index),
            record_camera_kind="usb",
            record_rtsp_url="",
        )
    url = (rtsp_url or "").strip()
    if not url:
        raise ValueError("rtsp_url required when use_usb is False")
    c = int(col)
    return replace(
        st,
        record_camera_kind="rtsp",
        record_rtsp_url=url,
        record_camera_index=0,
        decode_camera_index=STATION_RTSP_LOGICAL_ID_BASE + c,
    )
