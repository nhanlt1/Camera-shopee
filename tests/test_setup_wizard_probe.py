from packrecorder.ui.setup_wizard_probe import validate_rtsp_probe_result


def test_validate_rtsp_probe_result_fail_when_empty():
    ok, msg = validate_rtsp_probe_result(False, 0, 0)
    assert ok is False
    assert "không mở được" in msg.lower()


def test_validate_rtsp_probe_result_ok():
    ok, msg = validate_rtsp_probe_result(True, 1280, 720)
    assert ok is True
    assert "1280x720" in msg
