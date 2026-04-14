from __future__ import annotations

import time
import types

import pytest
from PySide6.QtCore import Qt


def test_worker_failed_when_hid_unavailable(monkeypatch: pytest.MonkeyPatch, qapp: object) -> None:
    import packrecorder.hid_pos_scan_worker as hpw

    monkeypatch.setattr(hpw, "_hid", None)
    w = hpw.HidPosScanWorker("s", "0C2E", "0B61")
    failed: list[tuple[str, str]] = []
    w.failed.connect(lambda sid, msg: failed.append((sid, msg)))
    w.run()
    assert len(failed) == 1
    assert failed[0][0] == "s"
    assert "hid" in failed[0][1].lower()


def test_worker_emits_line_with_hidapi_style_device_open(
    monkeypatch: pytest.MonkeyPatch, qtbot: pytest.QtBot
) -> None:
    """Gói hidapi: module hid có device().open(), không có Device()."""
    import packrecorder.hid_pos_scan_worker as hpw

    class Dev:
        def __init__(self) -> None:
            self.i = 0

        def open(self, vid: int, pid: int) -> None:
            pass

        def read(self, size: int, timeout: int | None = None) -> bytes:
            self.i += 1
            if self.i == 1:
                return bytes([1]) + b"XY\x00"
            time.sleep(0.02)
            return b""

        def close(self) -> None:
            pass

        def set_nonblocking(self, x: int) -> None:
            pass

    fake = types.SimpleNamespace()
    fake.device = lambda: Dev()

    monkeypatch.setattr(hpw, "_hid", fake)

    w = hpw.HidPosScanWorker("st2", "0C2E", "0B61")
    got: list[tuple[str, str]] = []
    w.line_decoded.connect(
        lambda sid, t: got.append((sid, t)),
        Qt.ConnectionType.DirectConnection,
    )
    w.start()
    qtbot.waitUntil(lambda: len(got) > 0, timeout=5000)
    w.stop_worker()
    assert w.wait(8000)
    assert got == [("st2", "XY")]


def test_worker_emits_line_with_mock_hid(
    monkeypatch: pytest.MonkeyPatch, qtbot: pytest.QtBot
) -> None:
    import packrecorder.hid_pos_scan_worker as hpw

    class Dev:
        def __init__(self, vid: int, pid: int) -> None:
            self.i = 0

        def read(self, size: int, timeout: int | None = None) -> bytes:
            self.i += 1
            if self.i == 1:
                return bytes([1]) + b"AB\x00"
            time.sleep(0.02)
            return b""

        def close(self) -> None:
            pass

    fake = types.SimpleNamespace()
    fake.Device = lambda vid, pid: Dev(vid, pid)

    monkeypatch.setattr(hpw, "_hid", fake)

    w = hpw.HidPosScanWorker("st", "0C2E", "0B61")
    got: list[tuple[str, str]] = []
    w.line_decoded.connect(
        lambda sid, t: got.append((sid, t)),
        Qt.ConnectionType.DirectConnection,
    )
    w.start()
    qtbot.waitUntil(lambda: len(got) > 0, timeout=5000)
    w.stop_worker()
    assert w.wait(8000)
    assert got == [("st", "AB")]
