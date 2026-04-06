import json
from pathlib import Path

from packrecorder.config import AppConfig, StationConfig, load_config, save_config


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
    assert c2.stations[0].decode_camera_index == 1


def test_station_for_decode_camera():
    from packrecorder.config import station_for_decode_camera

    st = [
        StationConfig("x", "Q1", 0, 0),
        StationConfig("y", "Q2", 1, 2),
    ]
    assert station_for_decode_camera(st, 0).station_id == "x"
    assert station_for_decode_camera(st, 2).station_id == "y"
    assert station_for_decode_camera(st, 9) is None


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
