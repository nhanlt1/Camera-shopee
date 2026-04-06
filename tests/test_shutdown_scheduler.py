from datetime import date, datetime, time, timedelta

from packrecorder.shutdown_scheduler import compute_next_shutdown_at, defer_one_hour


def test_next_shutdown_today_if_not_passed():
    cfg = time(18, 0)
    now = datetime(2026, 4, 6, 10, 0, 0)
    n = compute_next_shutdown_at(cfg, now)
    assert n == datetime(2026, 4, 6, 18, 0, 0)


def test_next_shutdown_tomorrow_if_passed():
    cfg = time(18, 0)
    now = datetime(2026, 4, 6, 19, 0, 0)
    n = compute_next_shutdown_at(cfg, now)
    assert n.date() == date(2026, 4, 7)


def test_defer_one_hour():
    base = datetime(2026, 4, 6, 18, 0, 0)
    assert defer_one_hour(base) == base + timedelta(hours=1)
