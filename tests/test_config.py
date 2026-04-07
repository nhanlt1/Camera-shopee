import json
from pathlib import Path

from packrecorder.config import (
    AppConfig,
    StationConfig,
    ensure_distinct_station_record_cameras,
    ensure_dual_stations,
    load_config,
    normalize_config,
    save_config,
    station_for_decode_camera,
    stations_non_serial_decode_collision,
)


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
