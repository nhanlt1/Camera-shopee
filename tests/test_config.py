import json
from pathlib import Path

from packrecorder.config import AppConfig, load_config, save_config


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
