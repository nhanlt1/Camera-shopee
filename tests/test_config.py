import json
from pathlib import Path

from packrecorder.config import (
    STATION_RTSP_LOGICAL_ID_BASE,
    AppConfig,
    StationConfig,
    ensure_distinct_station_record_cameras,
    ensure_dual_stations,
    load_config,
    normalize_config,
    save_config,
    station_for_decode_camera,
    station_record_cam_id,
    stations_non_serial_decode_collision,
)


def test_tray_background_fields_defaults() -> None:
    c = normalize_config(AppConfig())
    assert c.minimize_to_tray is False
    assert c.start_in_tray is False
    assert c.close_to_tray is True
    assert c.low_process_priority is False
    assert c.tray_show_toast_on_order is True
    assert c.tray_health_beep_interval_min == 0
    assert 0.0 <= c.tray_health_beep_volume <= 1.0
    assert c.enable_global_barcode_hook is False
    assert c.scanner_com_only is True


def test_scanner_usb_vid_pid_roundtrip_and_normalize(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    st = [
        StationConfig(
            "a1",
            "Máy A",
            0,
            0,
            scanner_usb_vid="0x0c2e",
            scanner_usb_pid="0b61",
        ),
        StationConfig(
            "b2",
            "Máy B",
            1,
            1,
            scanner_usb_vid="ZZZZ",
            scanner_usb_pid="12345",
        ),
    ]
    save_config(p, AppConfig(multi_camera_mode="stations", stations=st))
    c2 = load_config(p)
    assert c2.stations[0].scanner_usb_vid == "0C2E"
    assert c2.stations[0].scanner_usb_pid == "0B61"
    assert c2.stations[1].scanner_usb_vid == ""
    assert c2.stations[1].scanner_usb_pid == ""


def test_scanner_com_only_disables_global_hook() -> None:
    c = normalize_config(
        AppConfig(scanner_com_only=True, enable_global_barcode_hook=True)
    )
    assert c.scanner_com_only is True
    assert c.enable_global_barcode_hook is False


def test_start_in_tray_requires_minimize_to_tray() -> None:
    c = normalize_config(AppConfig(minimize_to_tray=False, start_in_tray=True))
    assert c.start_in_tray is False


def test_tray_fields_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    c = AppConfig(
        video_root=str(tmp_path / "v"),
        minimize_to_tray=True,
        start_in_tray=True,
        close_to_tray=False,
        tray_health_beep_interval_min=10,
        tray_health_beep_volume=0.25,
    )
    save_config(p, c)
    c2 = load_config(p)
    assert c2.minimize_to_tray is True
    assert c2.start_in_tray is True
    assert c2.close_to_tray is False
    assert c2.tray_health_beep_interval_min == 10
    assert abs(c2.tray_health_beep_volume - 0.25) < 1e-6


def test_disable_mp_via_env(monkeypatch) -> None:
    monkeypatch.setenv("PACKRECORDER_DISABLE_MP", "1")
    c = normalize_config(AppConfig(use_multiprocessing_camera_pipeline=True))
    assert c.use_multiprocessing_camera_pipeline is False


def test_use_multiprocessing_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    c = AppConfig(
        video_root=str(tmp_path / "v"),
        use_multiprocessing_camera_pipeline=False,
    )
    save_config(p, c)
    c2 = load_config(p)
    assert c2.use_multiprocessing_camera_pipeline is False


def test_default_record_resolution_and_encoding():
    c = AppConfig()
    c = normalize_config(c)
    assert c.use_multiprocessing_camera_pipeline is True
    assert c.record_resolution == "hd"
    assert c.record_fps == 30
    assert c.record_video_codec == "h264"
    assert c.record_h264_crf == 26
    assert c.record_video_bitrate_kbps == 3000
    assert c.barcode_scan_interval_frames == 15
    assert c.barcode_scan_scale == 0.5


def test_save_load(tmp_path: Path):
    p = tmp_path / "c.json"
    c = AppConfig(
        video_root=str(tmp_path / "v"),
        camera_index=0,
        packer_label="Máy 2",
    )
    save_config(p, c)
    c2 = load_config(p)
    assert c2.video_root == c.video_root
    assert c2.camera_index == 0
    assert c2.packer_label == "Máy 2"


def test_ha_fields_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "c.json"
    c = AppConfig(
        video_root=str(tmp_path / "v"),
        video_retention_keep_days=30,
        video_backup_root=str(tmp_path / "bak"),
        remote_status_json_path="Z:/Drive/status.json",
        status_json_relative="PackRecorder/status.json",
    )
    save_config(p, c)
    c2 = load_config(p)
    assert c2.video_retention_keep_days == 30
    assert c2.video_backup_root == str(tmp_path / "bak")
    assert c2.status_json_relative == "PackRecorder/status.json"
    assert Path(c2.remote_status_json_path) == tmp_path / "v" / "PackRecorder" / "status.json"


def test_record_roi_norm_roundtrip(tmp_path: Path):
    p = tmp_path / "c.json"
    roi = (0.1, 0.2, 0.5, 0.45)
    st = [
        StationConfig("a1", "Máy A", 0, 0, record_roi_norm=roi),
        StationConfig("b2", "Máy B", 1, 1, record_roi_norm=None),
    ]
    c = AppConfig(multi_camera_mode="stations", stations=st)
    save_config(p, c)
    c2 = load_config(p)
    assert c2.stations[0].record_roi_norm is not None
    assert len(c2.stations[0].record_roi_norm) == 4
    assert abs(c2.stations[0].record_roi_norm[0] - 0.1) < 1e-6
    assert c2.stations[1].record_roi_norm is None


def test_station_preview_display_roundtrip(tmp_path: Path):
    p = tmp_path / "c.json"
    st = [
        StationConfig(
            "a1",
            "Máy A",
            0,
            1,
            preview_display_index=2,
        ),
        StationConfig("b2", "Máy B", 1, 0, preview_display_index=-1),
    ]
    c = AppConfig(multi_camera_mode="stations", stations=st)
    save_config(p, c)
    c2 = load_config(p)
    assert c2.stations[0].preview_display_index == 2
    assert c2.stations[1].preview_display_index == -1


def test_save_load_stations_and_mode(tmp_path: Path):
    p = tmp_path / "c.json"
    st = [
        StationConfig("a1", "Máy A", 0, 1),
        StationConfig("b2", "Máy B", 1, 1),
    ]
    c = AppConfig(
        video_root=str(tmp_path / "v"),
        multi_camera_mode="stations",
        stations=st,
    )
    save_config(p, c)
    c2 = load_config(p)
    assert c2.multi_camera_mode == "stations"
    assert len(c2.stations) == 2
    assert c2.stations[0].packer_label == "Máy A"
    # decode 1 trùng camera ghi quầy B → normalize về camera ghi quầy A
    assert c2.stations[0].decode_camera_index == 0


def test_ensure_distinct_station_record_cameras():
    c = AppConfig(
        multi_camera_mode="stations",
        stations=[
            StationConfig("a", "M1", 2, 0),
            StationConfig("b", "M2", 2, 1),
        ],
    )
    ensure_distinct_station_record_cameras(c)
    assert c.stations[0].record_camera_index == 2
    assert c.stations[1].record_camera_index != 2


def test_ensure_dual_stations():
    c = AppConfig(multi_camera_mode="stations", stations=[])
    ensure_dual_stations(c)
    assert len(c.stations) == 2
    c2 = AppConfig(
        multi_camera_mode="stations",
        stations=[StationConfig("only", "A", 0, 0)],
    )
    ensure_dual_stations(c2)
    assert len(c2.stations) == 2
    extra = StationConfig("x", "X", 5, 5)
    c3 = AppConfig(
        multi_camera_mode="stations",
        stations=[
            StationConfig("a", "M1", 0, 0),
            StationConfig("b", "M2", 1, 1),
            extra,
        ],
    )
    ensure_dual_stations(c3)
    assert len(c3.stations) == 2
    assert c3.stations[0].station_id == "a"


def test_stations_non_serial_decode_collision():
    assert not stations_non_serial_decode_collision(
        [
            StationConfig("a", "M1", 0, 0),
            StationConfig("b", "M2", 1, 1),
        ]
    )
    assert stations_non_serial_decode_collision(
        [
            StationConfig("a", "M1", 0, 1),
            StationConfig("b", "M2", 1, 1),
        ]
    )
    assert not stations_non_serial_decode_collision(
        [
            StationConfig("a", "M1", 0, 1, scanner_serial_port="COM3"),
            StationConfig("b", "M2", 1, 1),
        ]
    )
    assert not stations_non_serial_decode_collision(
        [
            StationConfig("a", "M1", 0, 1, scanner_serial_port="COM3"),
            StationConfig("b", "M2", 1, 1, scanner_serial_port="COM4"),
        ]
    )


def test_station_for_decode_camera():
    st = [
        StationConfig("x", "Q1", 0, 0),
        StationConfig("y", "Q2", 1, 2),
    ]
    assert station_for_decode_camera(st, 0).station_id == "x"
    assert station_for_decode_camera(st, 2).station_id == "y"
    assert station_for_decode_camera(st, 9) is None

    st_serial = [
        StationConfig("x", "Q1", 0, 0, scanner_serial_port="COM3"),
        StationConfig("y", "Q2", 1, 2),
    ]
    assert station_for_decode_camera(st_serial, 0) is None
    assert station_for_decode_camera(st_serial, 2).station_id == "y"

    st_bad = [
        StationConfig("x", "Q1", 0, 0, scanner_serial_port="COM3"),
        StationConfig("y", "Q2", 1, 0),
    ]
    assert station_for_decode_camera(st_bad, 0) is None


def test_normalize_decode_not_peer_record():
    c = AppConfig(
        multi_camera_mode="stations",
        stations=[
            StationConfig("a", "Q1", 0, 0, scanner_serial_port="COM1"),
            StationConfig("b", "Q2", 1, 0),
        ],
    )
    normalize_config(c)
    assert c.stations[1].decode_camera_index == 1


def test_station_record_cam_id_rtsp_usb():
    u = StationConfig("a", "M1", 0, 0)
    r = StationConfig(
        "b",
        "M2",
        0,
        0,
        record_camera_kind="rtsp",
        record_rtsp_url="rtsp://x",
    )
    assert station_record_cam_id(u, 0) == 0
    assert station_record_cam_id(r, 1) == STATION_RTSP_LOGICAL_ID_BASE + 1


def test_rtsp_station_roundtrip(tmp_path: Path):
    p = tmp_path / "c.json"
    url = "rtsp://admin:pw@192.168.1.10:554/cam/realmonitor?channel=1&subtype=1"
    st = [
        StationConfig(
            "a1",
            "Máy A",
            0,
            0,
            record_camera_kind="rtsp",
            record_rtsp_url=url,
        ),
        StationConfig("b2", "Máy B", 1, 1),
    ]
    c = AppConfig(multi_camera_mode="stations", stations=st)
    save_config(p, c)
    c2 = load_config(p)
    assert c2.stations[0].record_camera_kind == "rtsp"
    assert url in (c2.stations[0].record_rtsp_url or "")
    assert c2.stations[0].record_camera_index == STATION_RTSP_LOGICAL_ID_BASE
    assert c2.stations[0].decode_camera_index == STATION_RTSP_LOGICAL_ID_BASE


def test_load_config_manual_json_rtsp(tmp_path: Path):
    """Sửa tay config.json (ngoài UI) phải đọc lại đúng kind + URL."""
    p = tmp_path / "manual.json"
    url = "rtsp://admin:secret@10.0.0.5:554/stream"
    raw = {
        "schema_version": 5,
        "multi_camera_mode": "stations",
        "stations": [
            {
                "station_id": "s0",
                "packer_label": "Ban 1",
                "record_camera_index": 0,
                "decode_camera_index": 0,
                "record_camera_kind": "rtsp",
                "record_rtsp_url": url,
            },
            {
                "station_id": "s1",
                "packer_label": "Ban 2",
                "record_camera_index": 1,
                "decode_camera_index": 1,
            },
        ],
    }
    p.write_text(json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
    c = load_config(p)
    assert c.stations[0].record_camera_kind == "rtsp"
    assert c.stations[0].record_rtsp_url == url


def test_save_load_utf8_packer(tmp_path: Path):
    p = tmp_path / "c.json"
    c = AppConfig(
        video_root=str(tmp_path / "v"),
        camera_index=0,
        packer_label="Nguyễn Văn A",
    )
    save_config(p, c)
    raw = p.read_text(encoding="utf-8")
    assert "Nguyễn" in raw
    assert "\\u" not in raw
    assert load_config(p).packer_label == "Nguyễn Văn A"
