"""Smoke tests cho burn-in video."""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np

from packrecorder.video_overlay import (
    RecordingBurnIn,
    burn_in_recording_info_bgr,
    format_datetime_vn,
    format_elapsed_hms,
    format_elapsed_overlay,
    render_recording_overlay_chip_rgba,
)


def test_format_vn_datetime() -> None:
    dt = datetime(2026, 4, 6, 15, 30, 5)
    assert format_datetime_vn(dt) == "2026-04-06  15:30:05"


def test_format_elapsed() -> None:
    t0 = datetime(2026, 1, 1, 10, 0, 0)
    assert format_elapsed_hms(t0, t0 + timedelta(seconds=5)) == "00:00:05"
    assert format_elapsed_hms(t0, t0 + timedelta(seconds=3665)) == "01:01:05"


def test_format_elapsed_overlay() -> None:
    t0 = datetime(2026, 4, 6, 15, 29, 55)
    assert format_elapsed_overlay(t0, t0 + timedelta(seconds=65)) == "01:05"
    assert format_elapsed_overlay(t0, t0 + timedelta(seconds=5)) == "00:05"
    assert format_elapsed_overlay(t0, t0 + timedelta(seconds=3665)) == "1:01:05"


def test_burn_in_smoke() -> None:
    bgr = np.zeros((120, 160, 3), dtype=np.uint8)
    ctx = RecordingBurnIn("ORD-1", "Quầy A", datetime(2026, 1, 1, 12, 0, 0))
    out = burn_in_recording_info_bgr(
        bgr,
        order=ctx.order,
        packer=ctx.packer,
        wall_now=datetime(2026, 1, 1, 12, 0, 10),
        started_at=ctx.started_at,
    )
    assert out.shape == bgr.shape
    assert not np.array_equal(out, bgr)


def test_overlay_chip_rgba_smoke() -> None:
    ctx = RecordingBurnIn("X1", "Máy 1", datetime(2026, 1, 1, 12, 0, 0))
    chip = render_recording_overlay_chip_rgba(
        order=ctx.order,
        packer=ctx.packer,
        wall_now=datetime(2026, 1, 1, 12, 0, 5),
        started_at=ctx.started_at,
    )
    if chip is None:
        return
    assert chip.ndim == 3 and chip.shape[2] == 4
    assert chip.shape[0] >= 8 and chip.shape[1] >= 8
    assert np.any(chip[:, :, 3] > 0)
