from packrecorder.ipc.capture_backoff import (
    CAPTURE_MAX_CONSECUTIVE_READ_FAILS,
    read_fail_backoff_seconds,
)


def test_backoff_sequence_caps_at_16() -> None:
    assert read_fail_backoff_seconds(1) == 1.0
    assert read_fail_backoff_seconds(2) == 2.0
    assert read_fail_backoff_seconds(3) == 4.0
    assert read_fail_backoff_seconds(4) == 8.0
    assert read_fail_backoff_seconds(5) == 16.0
    assert read_fail_backoff_seconds(99) == 16.0


def test_max_fails_positive() -> None:
    assert CAPTURE_MAX_CONSECUTIVE_READ_FAILS >= 10
