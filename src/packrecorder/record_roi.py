"""Normalized ROI (0..1) for station recording: crop preview / FFmpeg / pyzbar."""

from __future__ import annotations

import numpy as np

# yuv420p / libx264: even width and height.
_MIN_EVEN_DIM = 2


def clamp_norm_rect(
    x: float, y: float, w: float, h: float
) -> tuple[float, float, float, float]:
    """Clamp (x,y,w,h) to [0,1] with x+w<=1, y+h<=1 and positive area."""
    x = max(0.0, min(1.0, float(x)))
    y = max(0.0, min(1.0, float(y)))
    w = max(0.0, min(1.0, float(w)))
    h = max(0.0, min(1.0, float(h)))
    if x + w > 1.0:
        w = max(0.0, 1.0 - x)
    if y + h > 1.0:
        h = max(0.0, 1.0 - y)
    if w <= 0.0 or h <= 0.0:
        return (0.0, 0.0, 1.0, 1.0)
    return (x, y, w, h)


def norm_to_pixels(
    x: float,
    y: float,
    w: float,
    h: float,
    frame_w: int,
    frame_h: int,
    *,
    min_side_px: int = 4,
    even: bool = True,
) -> tuple[int, int, int, int]:
    """Map normalized ROI to pixel rect; optional even W/H for yuv420p."""
    fw = max(1, int(frame_w))
    fh = max(1, int(frame_h))
    xn, yn, wn, hn = clamp_norm_rect(x, y, w, h)
    px = int(round(xn * fw))
    py = int(round(yn * fh))
    pw = int(round(wn * fw))
    ph = int(round(hn * fh))
    px = max(0, min(fw - 1, px))
    py = max(0, min(fh - 1, py))
    pw = max(min_side_px, pw)
    ph = max(min_side_px, ph)
    if px + pw > fw:
        pw = fw - px
    if py + ph > fh:
        ph = fh - py
    pw = max(min_side_px, pw)
    ph = max(min_side_px, ph)
    if even:
        pw = max(_MIN_EVEN_DIM, pw & ~1)
        ph = max(_MIN_EVEN_DIM, ph & ~1)
        if px + pw > fw:
            px = max(0, fw - pw)
        if py + ph > fh:
            py = max(0, fh - ph)
    return (px, py, pw, ph)


def pixels_to_norm(
    px: int,
    py: int,
    pw: int,
    ph: int,
    frame_w: int,
    frame_h: int,
) -> tuple[float, float, float, float]:
    """Pixel rect → normalized (x,y,w,h)."""
    fw = max(1, int(frame_w))
    fh = max(1, int(frame_h))
    x = max(0.0, min(1.0, px / fw))
    y = max(0.0, min(1.0, py / fh))
    w = max(0.0, min(1.0, pw / fw))
    h = max(0.0, min(1.0, ph / fh))
    return clamp_norm_rect(x, y, w, h)


def crop_bgr_frame(frame: np.ndarray, x: int, y: int, w: int, h: int) -> np.ndarray:
    """Crop BGR numpy array; returns a contiguous copy suitable for tobytes()."""
    fh, fw = int(frame.shape[0]), int(frame.shape[1])
    x0 = max(0, min(fw - 1, int(x)))
    y0 = max(0, min(fh - 1, int(y)))
    x1 = max(x0 + 1, min(fw, x0 + int(w)))
    y1 = max(y0 + 1, min(fh, y0 + int(h)))
    out = np.ascontiguousarray(frame[y0:y1, x0:x1])
    return out
