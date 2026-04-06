from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

SoundMode = Literal["speaker", "scanner_host"]
MultiCameraMode = Literal["single", "stations", "pip"]


@dataclass
class StationConfig:
    station_id: str
    packer_label: str = "Máy 1"
    record_camera_index: int = 0
    decode_camera_index: int = 0


def default_stations() -> list[StationConfig]:
    return [
        StationConfig(str(uuid.uuid4()), "Máy 1", 0, 0),
        StationConfig(str(uuid.uuid4()), "Máy 2", 1, 1),
    ]


@dataclass
class AppConfig:
    schema_version: int = 2
    video_root: str = ""
    camera_index: int = 0
    packer_label: str = "Máy 1"
    ffmpeg_path: str = ""
    shutdown_enabled: bool = True
    shutdown_time_hhmm: str = "18:00"
    sound_enabled: bool = True
    sound_mode: SoundMode = "speaker"
    beep_short_ms: int = 120
    beep_gap_ms: int = 80
    beep_long_ms: int = 400
    wav_short_path: str = ""
    wav_double_path: str = ""
    wav_long_path: str = ""
    multi_camera_mode: MultiCameraMode = "single"
    stations: list[StationConfig] = field(default_factory=default_stations)
    pip_main_camera_index: int = 0
    pip_sub_camera_index: int = 1
    pip_decode_camera_index: int = 0
    pip_overlay_max_width: int = 320
    pip_overlay_margin: int = 10


def _station_from_dict(d: dict[str, Any]) -> StationConfig:
    known = {f.name for f in StationConfig.__dataclass_fields__.values()}
    kw = {k: v for k, v in d.items() if k in known}
    if "station_id" not in kw or not kw["station_id"]:
        kw["station_id"] = str(uuid.uuid4())
    return StationConfig(**kw)


def _config_to_dict(c: AppConfig) -> dict[str, Any]:
    d = asdict(c)
    return d


def _dict_to_config(d: dict[str, Any]) -> AppConfig:
    known = {f.name for f in AppConfig.__dataclass_fields__.values()}
    raw_stations = d.get("stations")
    stations: list[StationConfig] | None = None
    if isinstance(raw_stations, list):
        stations = []
        for item in raw_stations:
            if isinstance(item, dict):
                stations.append(_station_from_dict(item))
    filtered = {k: v for k, v in d.items() if k in known and k != "stations"}
    cfg = AppConfig(**filtered)
    if stations is not None:
        cfg.stations = stations if stations else default_stations()
    return cfg


def normalize_config(cfg: AppConfig) -> AppConfig:
    if cfg.multi_camera_mode == "stations" and not cfg.stations:
        cfg.stations = default_stations()
    for s in cfg.stations:
        if s.decode_camera_index < 0:
            s.decode_camera_index = 0
        if s.record_camera_index < 0:
            s.record_camera_index = 0
    if cfg.pip_main_camera_index == cfg.pip_sub_camera_index:
        cfg.pip_sub_camera_index = min(9, cfg.pip_main_camera_index + 1)
    return cfg


def save_config(path: Path, cfg: AppConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cfg = normalize_config(cfg)
    text = json.dumps(_config_to_dict(cfg), ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")


def load_config(path: Path) -> AppConfig:
    if not path.is_file():
        return normalize_config(AppConfig())
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return normalize_config(AppConfig())
    cfg = _dict_to_config(data)
    if cfg.schema_version < 2:
        cfg.schema_version = 2
    return normalize_config(cfg)


def default_config_path() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "PackRecorder" / "config.json"
    return Path.home() / ".packrecorder" / "config.json"


def station_for_decode_camera(
    stations: list[StationConfig], camera_index: int
) -> StationConfig | None:
    for s in stations:
        if s.decode_camera_index == camera_index:
            return s
    return None
