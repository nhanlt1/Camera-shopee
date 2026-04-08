"""Preset độ phân giải capture/ghi video (OpenCV → FFmpeg rawvideo)."""

from __future__ import annotations

from typing import Literal

import packrecorder.opencv_video  # noqa: F401 — env/log trước cv2 (config import sớm)

import cv2

RecordResolutionPreset = Literal["native", "vga", "hd", "full_hd"]

VALID_PRESETS: tuple[str, ...] = ("native", "vga", "hd", "full_hd")

PRESET_LABELS_VI: dict[str, str] = {
    "native": "Theo webcam (độ phân giải driver)",
    "vga": "VGA 640×480",
    "hd": "HD 1280×720",
    "full_hd": "Full HD 1920×1080",
}

PRESET_ORDER: tuple[str, ...] = ("native", "vga", "hd", "full_hd")


def normalize_record_resolution_preset(value: str) -> str:
    s = (value or "").strip().lower()
    if s in VALID_PRESETS:
        return s
    return "native"


def target_dimensions_for_preset(preset: str) -> tuple[int, int] | None:
    """None = không ép kích thước (giữ theo driver sau khi mở camera)."""
    p = normalize_record_resolution_preset(preset)
    if p == "native":
        return None
    if p == "vga":
        return (640, 480)
    if p == "hd":
        return (1280, 720)
    if p == "full_hd":
        return (1920, 1080)
    return (1280, 720)


def apply_capture_resolution(
    cap: cv2.VideoCapture, width: int, height: int
) -> tuple[int, int]:
    """Đặt CAP_PROP; trả về kích thước báo từ driver (có thể khác yêu cầu).

    Không ném exception: nếu set/read lỗi, trả về giá trị đọc được từ driver.
    """
    try:
        if width <= 0 or height <= 0:
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
            return w, h
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, float(width))
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, float(height))
        aw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        ah = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if aw <= 0:
            aw = width
        if ah <= 0:
            ah = height
        return aw, ah
    except Exception:
        try:
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or 640
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or 480
            return w, h
        except Exception:
            return 640, 480
