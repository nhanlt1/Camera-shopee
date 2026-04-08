import sys

from packrecorder.subprocess_win import popen_extra_kwargs, run_extra_kwargs


def test_extra_kwargs_platform_specific() -> None:
    d = popen_extra_kwargs()
    if sys.platform == "win32":
        assert "creationflags" in d
    else:
        assert d == {}
    assert isinstance(run_extra_kwargs(), dict)
