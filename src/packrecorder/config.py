from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

SoundMode = Literal["speaker", "scanner_host"]


@dataclass
class AppConfig:
    schema_version: int = 1
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


def _config_to_dict(c: AppConfig) -> dict[str, Any]:
    return asdict(c)


def _dict_to_config(d: dict[str, Any]) -> AppConfig:
    known = {f.name for f in AppConfig.__dataclass_fields__.values()}
    filtered = {k: v for k, v in d.items() if k in known}
    return AppConfig(**filtered)


def save_config(path: Path, cfg: AppConfig) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(_config_to_dict(cfg), ensure_ascii=False, indent=2)
    path.write_text(text, encoding="utf-8")


def load_config(path: Path) -> AppConfig:
    if not path.is_file():
        return AppConfig()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return AppConfig()
    return _dict_to_config(data)


def default_config_path() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "PackRecorder" / "config.json"
    return Path.home() / ".packrecorder" / "config.json"
