"""Chữ burn-in góc trên trái khung video (UTF-8, định dạng VN)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np

try:
    from PIL import Image, ImageDraw, ImageFont

    _HAS_PIL = True
except ImportError:
    Image = ImageDraw = ImageFont = None  # type: ignore[misc, assignment]
    _HAS_PIL = False

_PAD = 12
_FONT_SIZE = 30
# Nền sát chiều cao chữ: đệm ngang vừa, dọc tối thiểu
_BOX_PAD_X = 11
_BOX_PAD_Y = 5
_RADIUS = 12
# Nền đậm hơn và ít trong suốt để tránh bị chìm vào video.
_FILL_RGBA = (28, 34, 46, 230)
_OUTLINE_RGBA = (12, 16, 24, 220)
_TEXT_RGBA = (242, 246, 252, 255)
# Hệ số phủ khi không có Pillow (OpenCV)
_CV2_OVERLAY_ALPHA = 0.68
_UI_CHIP_SCALE = 0.66


@dataclass(frozen=True)
class RecordingBurnIn:
    order: str
    packer: str
    started_at: datetime


def _load_font(size: int) -> Any:
    assert ImageFont is not None
    windir = os.environ.get("WINDIR", r"C:\Windows")
    candidates = [
        Path(windir) / "Fonts" / "seguisb.ttf",
        Path(windir) / "Fonts" / "arialbd.ttf",
        Path(windir) / "Fonts" / "tahomabd.ttf",
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
    """
    Ngày giờ trên video: năm-tháng-ngày + giờ phút giây (ISO 8601).
    Dễ đọc, không nhầm thứ tự ngày/tháng, dễ tìm/sắp xếp khi xem lại file.
    """
    return dt.strftime("%Y-%m-%d  %H:%M:%S")


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
    return f"{order} · {packer} · {dt_vn} · {elapsed}"


def _burnin_lru_key(
    order: str, packer: str, wall_now: datetime, started_at: datetime
) -> tuple[str, str, str, str]:
    ws = snap_wall_clock_to_second(wall_now)
    ss = started_at.replace(microsecond=0)
    return (order, packer, ws.isoformat(), ss.isoformat())


def _build_chip_rgba_for_line(line: str) -> np.ndarray:
    """RGBA HxWx4, kích thước vừa vùng chip (nền + một dòng)."""
    assert Image is not None and ImageDraw is not None
    tmp = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(tmp)
    font = _font()
    bb = tdraw.textbbox((0, 0), line, font=font)
    text_w = bb[2] - bb[0]
    text_h = bb[3] - bb[1]
    bw = max(4, text_w + _BOX_PAD_X * 2)
    bh = max(4, text_h + _BOX_PAD_Y * 2)
    img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    x1, y1 = bw - 1, bh - 1
    if hasattr(draw, "rounded_rectangle"):
        draw.rounded_rectangle(
            [0, 0, x1, y1],
            radius=_RADIUS,
            fill=_FILL_RGBA,
            outline=_OUTLINE_RGBA,
            width=1,
        )
    else:
        draw.rectangle(
            [0, 0, x1, y1],
            fill=_FILL_RGBA,
            outline=_OUTLINE_RGBA,
            width=1,
        )
    tx = _BOX_PAD_X - bb[0]
    ty = _BOX_PAD_Y - bb[1]
    draw.text((tx, ty), line, font=font, fill=_TEXT_RGBA)
    return np.ascontiguousarray(np.asarray(img, dtype=np.uint8))


def _build_chip_rgba_for_line_ui(line: str) -> np.ndarray:
    """Chip cho UI: giữ style nhưng nhỏ hơn để đỡ che preview."""
    assert Image is not None and ImageDraw is not None
    tmp = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    tdraw = ImageDraw.Draw(tmp)
    font = _load_font(max(12, int(round(_FONT_SIZE * _UI_CHIP_SCALE))))
    bb = tdraw.textbbox((0, 0), line, font=font)
    text_w = bb[2] - bb[0]
    text_h = bb[3] - bb[1]
    pad_x = max(4, int(round(_BOX_PAD_X * _UI_CHIP_SCALE)))
    pad_y = max(2, int(round(_BOX_PAD_Y * _UI_CHIP_SCALE)))
    radius = max(5, int(round(_RADIUS * _UI_CHIP_SCALE)))
    bw = max(4, text_w + pad_x * 2)
    bh = max(4, text_h + pad_y * 2)
    img = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")
    x1, y1 = bw - 1, bh - 1
    if hasattr(draw, "rounded_rectangle"):
        draw.rounded_rectangle(
            [0, 0, x1, y1],
            radius=radius,
            fill=_FILL_RGBA,
            outline=_OUTLINE_RGBA,
            width=1,
        )
    else:
        draw.rectangle(
            [0, 0, x1, y1],
            fill=_FILL_RGBA,
            outline=_OUTLINE_RGBA,
            width=1,
        )
    tx = pad_x - bb[0]
    ty = pad_y - bb[1]
    draw.text((tx, ty), line, font=font, fill=_TEXT_RGBA)
    return np.ascontiguousarray(np.asarray(img, dtype=np.uint8))


@lru_cache(maxsize=64)
def _cached_chip_rgba_by_key(
    order: str, packer: str, wall_iso: str, started_iso: str
) -> np.ndarray:
    wall_dt = datetime.fromisoformat(wall_iso)
    started_dt = datetime.fromisoformat(started_iso)
    line = _single_line_vi(order, packer, wall_dt, started_dt)
    return _build_chip_rgba_for_line(line)


@lru_cache(maxsize=64)
def _cached_chip_rgba_ui_by_key(
    order: str, packer: str, wall_iso: str, started_iso: str
) -> np.ndarray:
    wall_dt = datetime.fromisoformat(wall_iso)
    started_dt = datetime.fromisoformat(started_iso)
    line = _single_line_vi(order, packer, wall_dt, started_dt)
    return _build_chip_rgba_for_line_ui(line)


def _chip_rgba_cached(
    order: str, packer: str, wall_now: datetime, started_at: datetime
) -> np.ndarray:
    k = _burnin_lru_key(order, packer, wall_now, started_at)
    return _cached_chip_rgba_by_key(k[0], k[1], k[2], k[3])


def _chip_rgba_ui_cached(
    order: str, packer: str, wall_now: datetime, started_at: datetime
) -> np.ndarray:
    k = _burnin_lru_key(order, packer, wall_now, started_at)
    return _cached_chip_rgba_ui_by_key(k[0], k[1], k[2], k[3])


def _composite_chip_bgr(bgr: np.ndarray, chip_rgba: np.ndarray, x0: int, y0: int) -> None:
    """Alpha-blend chip lên bgr tại (x0,y0), góc trên-trái. Sửa tại chỗ."""
    bh, bw = chip_rgba.shape[:2]
    H, W = bgr.shape[:2]
    if x0 >= W or y0 >= H or x0 + bw <= 0 or y0 + bh <= 0:
        return
    sx0 = max(0, x0)
    sy0 = max(0, y0)
    cx0 = sx0 - x0
    cy0 = sy0 - y0
    sx1 = min(W, x0 + bw)
    sy1 = min(H, y0 + bh)
    cw = sx1 - sx0
    ch = sy1 - sy0
    if cw <= 0 or ch <= 0:
        return
    roi = bgr[sy0:sy1, sx0:sx1].astype(np.float32)
    sub = chip_rgba[cy0 : cy0 + ch, cx0 : cx0 + cw]
    a = sub[:, :, 3:4].astype(np.float32) / 255.0
    rgb = sub[:, :, :3].astype(np.float32)
    bgr_px = rgb[:, :, ::-1]
    roi[:] = roi * (1.0 - a) + bgr_px * a
    bgr[sy0:sy1, sx0:sx1] = np.clip(roi, 0, 255).astype(np.uint8)


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
    scale = 0.75
    thick = 2
    (tw, th), bl = cv2.getTextSize(line, font, scale, thick)
    text_h = th + bl
    box_w = tw + _BOX_PAD_X * 2
    box_h = text_h + _BOX_PAD_Y * 2
    x0, y0 = _PAD, _PAD
    h, w = out.shape[:2]
    x1 = min(w - 1, x0 + box_w)
    y1 = min(h - 1, y0 + box_h)
    fill_bgr = np.array([42, 36, 28], dtype=np.float32)
    roi = out[y0:y1, x0:x1].astype(np.float32)
    mask3 = np.zeros((y1 - y0, x1 - x0, 3), dtype=np.uint8)
    _cv2_fill_rounded_rect(mask3, 0, 0, x1 - x0, y1 - y0, (255, 255, 255), _RADIUS)
    m = (mask3[:, :, 0].astype(np.float32) / 255.0)[..., np.newaxis]
    blend_a = _CV2_OVERLAY_ALPHA * m
    roi[:] = roi * (1.0 - blend_a) + fill_bgr * blend_a
    out[y0:y1, x0:x1] = np.clip(roi, 0, 255).astype(np.uint8)
    tx = x0 + _BOX_PAD_X
    ty = y0 + _BOX_PAD_Y + th
    cv2.putText(out, line, (tx, ty), font, scale, (240, 244, 248), thick, cv2.LINE_AA)
    return out


def _burn_in_pil_fast(
    bgr: np.ndarray,
    *,
    order: str,
    packer: str,
    wall_now: datetime,
    started_at: datetime,
) -> np.ndarray:
    assert Image is not None
    out = np.ascontiguousarray(bgr.copy())
    chip = _chip_rgba_cached(order, packer, wall_now, started_at)
    _composite_chip_bgr(out, chip, _PAD, _PAD)
    return out


def render_recording_overlay_chip_rgba(
    *,
    order: str,
    packer: str,
    wall_now: datetime,
    started_at: datetime,
) -> np.ndarray | None:
    """
    Chip RGBA (chỉ vùng nền + chữ), cùng kiểu với burn-in video — dùng trên UI khi đang quay.
    Trả về None nếu không có Pillow.
    """
    if not _HAS_PIL or Image is None:
        return None
    return _chip_rgba_ui_cached(order, packer, wall_now, started_at).copy()


def burn_in_recording_info_bgr(
    bgr: np.ndarray,
    *,
    order: str,
    packer: str,
    wall_now: datetime,
    started_at: datetime,
) -> np.ndarray:
    """
    Một dòng góc trên trái: mã đơn · quầy · dd/mm/yyyy HH:MM:SS · MM:SS.
    Pillow: cache theo giây (Unicode), chỉ blend vùng chip lên BGR. Không Pillow: OpenCV.
    """
    if bgr.ndim != 3 or bgr.shape[2] != 3:
        return bgr
    h, w = bgr.shape[:2]
    if h < 16 or w < 16:
        return bgr

    if _HAS_PIL:
        return _burn_in_pil_fast(
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
