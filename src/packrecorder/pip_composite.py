from __future__ import annotations

import numpy as np


def composite_pip_bgr(
    main_bgr: np.ndarray,
    sub_bgr: np.ndarray,
    *,
    sub_max_width: int = 320,
    margin: int = 10,
) -> np.ndarray:
    """Overlay sub picture-in-picture on bottom-right of main (BGR uint8)."""
    mh, mw = main_bgr.shape[:2]
    sh, sw = sub_bgr.shape[:2]
    if sw <= 0 or sh <= 0 or mw <= 0 or mh <= 0:
        return main_bgr.copy()
    target_w = min(sub_max_width, max(1, mw // 4))
    target_h = max(1, int(sh * (target_w / sw)))
    if target_h > mh - 2 * margin:
        target_h = max(1, mh - 2 * margin)
        target_w = max(1, int(sw * (target_h / sh)))
    small = _cv2_resize(sub_bgr, target_w, target_h)
    th, tw = small.shape[:2]
    out = main_bgr.copy()
    y0 = max(0, mh - th - margin)
    x0 = max(0, mw - tw - margin)
    out[y0 : y0 + th, x0 : x0 + tw] = small
    return out


def _cv2_resize(arr: np.ndarray, w: int, h: int) -> np.ndarray:
    try:
        import cv2

        return cv2.resize(arr, (w, h), interpolation=cv2.INTER_AREA)
    except Exception:
        # Fallback without cv2 (tests): nearest-neighbor via numpy
        from numpy import kron

        sh, sw = arr.shape[:2]
        zx, zy = max(1, w // sw), max(1, h // sh)
        scaled = kron(arr, np.ones((zy, zx, 1), dtype=arr.dtype))
        return scaled[:h, :w, :].copy()
