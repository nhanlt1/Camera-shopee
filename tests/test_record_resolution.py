from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from packrecorder.record_resolution import (
    apply_capture_resolution,
    normalize_record_resolution_preset,
    target_dimensions_for_preset,
)


def test_normalize_defaults_to_native():
    assert normalize_record_resolution_preset("") == "native"
    assert normalize_record_resolution_preset("  ") == "native"
    assert normalize_record_resolution_preset("bogus") == "native"


def test_normalize_accepts_known():
    assert normalize_record_resolution_preset("NATIVE") == "native"
    assert normalize_record_resolution_preset("Full_HD") == "full_hd"


def test_target_dimensions():
    assert target_dimensions_for_preset("native") is None
    assert target_dimensions_for_preset("vga") == (640, 480)
    assert target_dimensions_for_preset("hd") == (1280, 720)
    assert target_dimensions_for_preset("full_hd") == (1920, 1080)


def test_apply_capture_resolution_sets_props():
    cv2 = pytest.importorskip("cv2")
    cap = MagicMock()
    cap.get.side_effect = [1280.0, 720.0]
    w, h = apply_capture_resolution(cap, 1280, 720)
    assert (w, h) == (1280, 720)
    cap.set.assert_called()
    assert cap.set.call_args_list[0][0][0] == cv2.CAP_PROP_FRAME_WIDTH


def test_apply_capture_resolution_never_raises():
    cv2 = pytest.importorskip("cv2")
    cap = MagicMock()
    cap.set.side_effect = RuntimeError("driver")
    cap.get.side_effect = [800.0, 600.0]
    w, h = apply_capture_resolution(cap, 1920, 1080)
    assert (w, h) == (800, 600)
