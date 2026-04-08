"""Unit tests for serial scan queue (drop-oldest policy)."""

from __future__ import annotations

import queue

from packrecorder.serial_scan_worker import put_scan_line_drop_oldest


def test_put_scan_line_drop_oldest_never_exceeds_maxsize() -> None:
    q: queue.Queue = queue.Queue(maxsize=4)
    for i in range(20):
        put_scan_line_drop_oldest(q, "st", f"x{i}")
        assert q.qsize() <= 4


def test_put_scan_line_drop_oldest_drops_oldest_fifo() -> None:
    q: queue.Queue = queue.Queue(maxsize=2)
    put_scan_line_drop_oldest(q, "a", "1")
    put_scan_line_drop_oldest(q, "a", "2")
    drops: list[int] = []
    put_scan_line_drop_oldest(q, "a", "3", on_drop=lambda: drops.append(1))
    assert q.qsize() == 2
    assert drops == [1]
    assert q.get_nowait() == ("a", "2")
    assert q.get_nowait() == ("a", "3")
