import sys

from packrecorder.shm_cleanup import cleanup_stale_packrecorder_shm


def test_cleanup_no_crash() -> None:
    n = cleanup_stale_packrecorder_shm()
    assert n >= 0
    if sys.platform == "win32":
        assert n == 0
