import time

from packrecorder.ipc.health import is_stale


def test_is_stale_disabled_when_threshold_zero() -> None:
    assert not is_stale(1.0, time.time(), 0.0)


def test_is_stale_false_when_never_beat() -> None:
    assert not is_stale(0.0, time.time(), 5.0)


def test_is_stale_true_when_old() -> None:
    now = 1000.0
    assert is_stale(now - 10.0, now, 5.0)
