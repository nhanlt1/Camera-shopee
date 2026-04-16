from packrecorder.config import STATION_RTSP_LOGICAL_ID_BASE, StationConfig
from packrecorder.ui.setup_wizard_camera import apply_wizard_camera_station


def test_apply_usb():
    st = StationConfig("id", "Máy 1", 0, 0)
    out = apply_wizard_camera_station(
        st, 0, use_usb=True, usb_index=2, rtsp_url=""
    )
    assert out.record_camera_kind == "usb"
    assert out.record_camera_index == 2
    assert out.decode_camera_index == 2
    assert out.record_rtsp_url == ""


def test_apply_rtsp():
    st = StationConfig("id", "Máy 1", 0, 0)
    out = apply_wizard_camera_station(
        st,
        1,
        use_usb=False,
        usb_index=0,
        rtsp_url="rtsp://192.168.1.10/stream",
    )
    assert out.record_camera_kind == "rtsp"
    assert out.record_rtsp_url == "rtsp://192.168.1.10/stream"
    assert out.record_camera_index == 0
    assert out.decode_camera_index == STATION_RTSP_LOGICAL_ID_BASE + 1


def test_apply_rtsp_empty_raises():
    st = StationConfig("id", "Máy 1", 0, 0)
    try:
        apply_wizard_camera_station(st, 0, use_usb=False, usb_index=0, rtsp_url="  ")
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError")
