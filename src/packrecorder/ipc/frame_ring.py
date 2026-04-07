"""Layout byte và numpy view cho vòng đệm BGR trong SharedMemory."""

from __future__ import annotations

import multiprocessing.shared_memory as sm
from typing import Optional

import numpy as np


def slot_nbytes(height: int, width: int) -> int:
    return int(height * width * 3)


def ring_nbytes(height: int, width: int, n_slots: int) -> int:
    return slot_nbytes(height, width) * int(n_slots)


def slot_offset(slot_idx: int, height: int, width: int) -> int:
    return int(slot_idx) * slot_nbytes(height, width)


def ndarray_slot(
    shared: sm.SharedMemory,
    slot_idx: int,
    height: int,
    width: int,
) -> np.ndarray:
    off = slot_offset(slot_idx, height, width)
    return np.ndarray(
        (height, width, 3),
        dtype=np.uint8,
        buffer=shared.buf,
        offset=off,
    )


def create_ring_shm(height: int, width: int, n_slots: int) -> sm.SharedMemory:
    size = ring_nbytes(height, width, n_slots)
    return sm.SharedMemory(create=True, size=size)


def attach_ring_shm(name: str) -> sm.SharedMemory:
    return sm.SharedMemory(name=name)


def close_unlink(shm: Optional[sm.SharedMemory]) -> None:
    if shm is None:
        return
    try:
        shm.close()
    except BufferError:
        pass
    try:
        shm.unlink()
    except FileNotFoundError:
        pass
