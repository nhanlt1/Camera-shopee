"""Shared memory ring layout (single process)."""

from __future__ import annotations

import multiprocessing.shared_memory as sm

import numpy as np

from packrecorder.ipc.frame_ring import (
    ndarray_slot,
    ring_nbytes,
    slot_nbytes,
    slot_offset,
)


def test_slot_layout_math():
    assert slot_nbytes(480, 640) == 640 * 480 * 3
    assert ring_nbytes(480, 640, 3) == 640 * 480 * 3 * 3
    assert slot_offset(1, 2, 4) == slot_nbytes(2, 4)


def test_roundtrip_write_read_slot():
    h, w, n = 4, 6, 2
    size = ring_nbytes(h, w, n)
    shm = sm.SharedMemory(create=True, size=size)
    try:
        v0 = ndarray_slot(shm, 0, h, w)
        v1 = ndarray_slot(shm, 1, h, w)
        v0[:] = 42
        v1[:] = 99
        assert v0[0, 0, 1] == 42
        assert v1[2, 3, 2] == 99
    finally:
        shm.close()
        shm.unlink()
