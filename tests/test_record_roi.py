"""Unit tests for packrecorder.record_roi."""

from __future__ import annotations

import numpy as np

from packrecorder.record_roi import (
    clamp_norm_rect,
    crop_bgr_frame,
    norm_to_pixels,
    pixels_to_norm,
)


def test_clamp_norm_rect():
    assert clamp_norm_rect(-0.1, 0.2, 0.5, 0.5) == (0.0, 0.2, 0.5, 0.5)
    assert clamp_norm_rect(0.5, 0.5, 0.6, 0.6) == (0.5, 0.5, 0.5, 0.5)


def test_norm_to_pixels_full_frame_even():
    x, y, w, h = norm_to_pixels(0, 0, 1, 1, 640, 480, even=True)
    assert x == 0 and y == 0
    assert w % 2 == 0 and h % 2 == 0
    assert w <= 640 and h <= 480


def test_pixels_to_norm_roundtrip():
    fw, fh = 1280, 720
    t = pixels_to_norm(100, 50, 800, 600, fw, fh)
    px, py, pw, ph = norm_to_pixels(t[0], t[1], t[2], t[3], fw, fh, even=False)
    assert abs(px - 100) <= 1
    assert abs(py - 50) <= 1


def test_crop_bgr_frame_shape():
    frame = np.zeros((480, 640, 3), dtype=np.uint8)
    out = crop_bgr_frame(frame, 10, 20, 100, 80)
    assert out.shape == (80, 100, 3)
    assert out.flags["C_CONTIGUOUS"]
