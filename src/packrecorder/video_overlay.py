"""Chữ burn-in góc trên trái khung video (UTF-8, định dạng VN)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

try:
    from PIL import Image, ImageDraw, ImageFont

    _HAS_PIL = True
except ImportError:
    Image = ImageDraw = ImageFont = None  # type: ignore[misc, assignment]
    _HAS_PIL = False

_PAD = 10
_FONT_SIZE = 20
_BOX_PAD = 10
_RADIUS = 12
# Nền nhạt (RGBA), chữ đậm vừa để đọc trên nền sáng
_FILL_RGBA = (245, 247, 252, 238)
_OUTLINE_RGBA = (210, 218, 230, 220)
_TEXT_RGBA = (28, 32, 42, 255)


@dataclass(frozen=True)
class RecordingBurnIn:
    order: str
    packer: str
    started_at: datetime


def _load_font(size: int) -> Any:
    assert ImageFont is not None
    windir = os.environ.get("WINDIR", r"C:\Windows")
    candidates = [
        Path(windir) / "Fonts" / "segoeui.ttf",
        Path(windir) / "Fonts" / "arial.ttf",
        Path(windir) / "Fonts" / "tahoma.ttf",
    ]
    for p in candidates:
        if p.is_file():
            try:
                return ImageFont.truetype(str(p), size=size)
            except OSError:
                continue
    return ImageFont.load_default()


_FONT: Any = None


def _font() -> Any:
    global _FONT
    assert ImageFont is not None
    if _FONT is None:
        _FONT = _load_font(_FONT_SIZE)
    return _FONT


def format_datetime_vn(dt: datetime) -> str:
    """Ngày giờ kiểu thường dùng tại VN."""
    return dt.strftime("%d/%m/%Y %H:%M:%S")


def format_elapsed_hms(started_at: datetime, now: datetime) -> str:
    secs = max(0, int((now - started_at).total_seconds()))
    h, r = divmod(secs, 3600)
    m, s = divmod(r, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def format_elapsed_overlay(started_at: datetime, now: datetime) -> str:
    """Thời lượng trên overlay/UI: MM:SS; từ 1 giờ trở lên: H:MM:SS (vd. 01:05, 1:05:03)."""
    secs = max(0, int((now - started_at).total_seconds()))
    if secs >= 3600:
        h, r = divmod(secs, 3600)
        m, s = divmod(r, 60)
        return f"{h}:{m:02d}:{s:02d}"
    m, s = divmod(secs, 60)
    return f"{m:02d}:{s:02d}"


def snap_wall_clock_to_second(now: datetime) -> datetime:
    """Giờ hiển thị chỉ đổi mỗi giây (không nhảy theo micro giây), khớp mốc đồng hồ."""
    return now.replace(microsecond=0)


def _single_line_vi(order: str, packer: str, wall_now: datetime, started_at: datetime) -> str:
    wall_snap = snap_wall_clock_to_second(wall_now)
    dt_vn = format_datetime_vn(wall_snap)
    elapsed = format_elapsed_overlay(started_at, wall_snap)
    return f"Đơn {order} · {packer} · {dt_vn} · {elapsed}"


def _ascii_safe(s: str, limit: int = 120) -> str:
    t = s.encode("ascii", "replace").decode("ascii")
    return t if len(t) <= limit else t[: limit - 1] + "?"


def _single_line_cv2(
    order: str, packer: str, wall_now: datetime, started_at: datetime
) -> str:
    wall_snap = snap_wall_clock_to_second(wall_now)
    dt_vn = format_datetime_vn(wall_snap)
    elapsed = format_elapsed_overlay(started_at, wall_snap)
    return f"{_ascii_safe(order)} | {_ascii_safe(packer)} | {dt_vn} | {elapsed}"


def _cv2_fill_rounded_rect(
    img: np.ndarray, x0: int, y0: int, x1: int, y1: int, bgr: tuple[int, int, int], r: int
) -> None:
    import cv2

    r = max(0, min(r, (x1 - x0) // 2, (y1 - y0) // 2))
    if r <= 0:
        cv2.rectangle(img, (x0, y0), (x1, y1), bgr, -1)
        return
    cv2.rectangle(img, (x0 + r, y0), (x1 - r, y1), bgr, -1)
    cv2.rectangle(img, (x0, y0 + r), (x1, y1 - r), bgr, -1)
    cv2.ellipse(img, (x0 + r, y0 + r), (r, r), 180, 0, 90, bgr, -1)
    cv2.ellipse(img, (x1 - r, y0 + r), (r, r), 270, 0, 90, bgr, -1)
    cv2.ellipse(img, (x1 - r, y1 - r), (r, r), 0, 0, 90, bgr, -1)
    cv2.ellipse(img, (x0 + r, y1 - r), (r, r), 90, 0, 90, bgr, -1)


def _burn_in_cv2(
    bgr: np.ndarray,
    *,
    order: str,
    packer: str,
    wall_now: datetime,
    started_at: datetime,
) -> np.ndarray:
    import cv2

    out = np.ascontiguousarray(bgr)
    line = _single_line_cv2(order, packer, wall_now, started_at)
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.5
    thick = 1
    (tw, th), bl = cv2.getTextSize(line, font, scale, thick)
    text_h = th + bl
    box_w = tw + _BOX_PAD * 2
    box_h = text_h + _BOX_PAD * 2
    x0, y0 = _PAD, _PAD
    h, w = out.shape[:2]
    x1 = min(w - 1, x0 + box_w)
    y1 = min(h - 1, y0 + box_h)
    # Nền nhạt BGR (tương đương _FILL_RGBA)
    fill_bgr = (252, 247, 245)
    _cv2_fill_rounded_rect(out, x0, y0, x1, y1, fill_bgr, _RADIUS)
    tx = x0 + _BOX_PAD
    ty = y0 + _BOX_PAD + th
    cv2.putText(out, line, (tx, ty), font, scale, (32, 30, 28), thick, cv2.LINE_AA)
    return out


def _burn_in_pil(
    bgr: np.ndarray,
    *,
    order: str,
    packer: str,
    wall_now: datetime,
    started_at: datetime,
) -> np.ndarray:
    assert Image is not None and ImageDraw is not None
    h, w = bgr.shape[:2]
    line = _single_line_vi(order, packer, wall_now, started_at)

    rgb = bgr[:, :, ::-1].copy()
    img = Image.fromarray(rgb)
    draw = ImageDraw.Draw(img, "RGBA")
    font = _font()
    bb = draw.textbbox((0, 0), line, font=font)
    text_w = bb[2] - bb[0]
    text_h = bb[3] - bb[1]
    x0, y0 = _PAD, _PAD
    x1 = min(w - 1, x0 + text_w + _BOX_PAD * 2)
    y1 = min(h - 1, y0 + text_h + _BOX_PAD * 2)

    if hasattr(draw, "rounded_rectangle"):
        draw.rounded_rectangle(
            [x0, y0, x1, y1],
            radius=_RADIUS,
            fill=_FILL_RGBA,
            outline=_OUTLINE_RGBA,
            width=1,
        )
    else:
        draw.rectangle(
            [x0, y0, x1, y1],
            fill=_FILL_RGBA,
            outline=_OUTLINE_RGBA,
            width=1,
        )

    tx = x0 + _BOX_PAD - bb[0]
    ty = y0 + _BOX_PAD - bb[1]
    draw.text((tx, ty), line, font=font, fill=_TEXT_RGBA)

    out_rgb = np.asarray(img.convert("RGB"), dtype=np.uint8)
    return out_rgb[:, :, ::-1].copy()


def burn_in_recording_info_bgr(
    bgr: np.ndarray,
    *,
    order: str,
    packer: str,
    wall_now: datetime,
    started_at: datetime,
) -> np.ndarray:
    """
    Một dòng góc trên trái: Đơn … · quầy · dd/mm/yyyy HH:MM:SS · MM:SS.
    Nền nhạt bo tròn (Pillow). Không Pillow: OpenCV, một dòng tương đương.
    """
    if bgr.ndim != 3 or bgr.shape[2] != 3:
        return bgr
    h, w = bgr.shape[:2]
    if h < 16 or w < 16:
        return bgr

    if _HAS_PIL:
        return _burn_in_pil(
            bgr,
            order=order,
            packer=packer,
            wall_now=wall_now,
            started_at=started_at,
        )
    return _burn_in_cv2(
        bgr,
        order=order,
        packer=packer,
        wall_now=wall_now,
        started_at=started_at,
    )
