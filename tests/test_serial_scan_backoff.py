from packrecorder.serial_scan_worker import _serial_reopen_backoff_seconds


def test_serial_backoff_capped() -> None:
    assert _serial_reopen_backoff_seconds(1) == 0.25
    assert _serial_reopen_backoff_seconds(2) == 0.5
    assert _serial_reopen_backoff_seconds(10) == 8.0
