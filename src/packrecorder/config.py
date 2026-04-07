from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field, replace
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
    # Máy quét mã USB dạng serial (COM). Rỗng = đọc mã bằng camera + pyzbar.
    scanner_serial_port: str = ""
    scanner_serial_baud: int = 9600


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
    multi_camera_mode: MultiCameraMode = "stations"
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


def ensure_dual_stations(cfg: AppConfig) -> None:
    """Giao diện chính 2 cột: luôn đúng 2 quầy khi chế độ stations."""
    if cfg.multi_camera_mode != "stations":
        return
    while len(cfg.stations) < 2:
        n = len(cfg.stations)
        cfg.stations.append(
            StationConfig(str(uuid.uuid4()), f"Máy {n + 1}", min(n, 9), min(n, 9))
        )
    if len(cfg.stations) > 2:
        cfg.stations[:] = cfg.stations[:2]


def ensure_decode_camera_not_peer_record(cfg: AppConfig) -> None:
    """
    Quầy đọc mã bằng camera không được dùng cùng index với camera GHI của quầy kia.

    Nếu không: luồng pyzbar trên camera ghi quầy A vẫn chạy (A dùng COM) và mã trong
    khung quay A bị gán nhầm cho quầy B khi B chọn «đọc mã» trùng camera đó.
    """
    if cfg.multi_camera_mode != "stations" or len(cfg.stations) < 2:
        return
    for _ in range(3):
        changed = False
        for i in range(2):
            st = cfg.stations[i]
            if station_uses_serial_scanner(st):
                continue
            other = cfg.stations[1 - i]
            if st.decode_camera_index == other.record_camera_index:
                cfg.stations[i] = replace(
                    st, decode_camera_index=st.record_camera_index
                )
                changed = True
        if not changed:
            break


def ensure_distinct_station_record_cameras(cfg: AppConfig) -> None:
    """Hai quầy không dùng chung một camera ghi (tránh một webcam hiện ở cả hai cột)."""
    if cfg.multi_camera_mode != "stations" or len(cfg.stations) < 2:
        return
    a = cfg.stations[0].record_camera_index
    b = cfg.stations[1].record_camera_index
    if a != b:
        return
    for alt in range(10):
        if alt != a:
            s1 = cfg.stations[1]
            cfg.stations[1] = replace(s1, record_camera_index=alt)
            return


def normalize_config(cfg: AppConfig) -> AppConfig:
    if cfg.multi_camera_mode == "stations" and not cfg.stations:
        cfg.stations = default_stations()
    for s in cfg.stations:
        if s.decode_camera_index < 0:
            s.decode_camera_index = 0
        if s.record_camera_index < 0:
            s.record_camera_index = 0
        if s.scanner_serial_baud < 1200 or s.scanner_serial_baud > 921600:
            s.scanner_serial_baud = 9600
    ensure_distinct_station_record_cameras(cfg)
    ensure_decode_camera_not_peer_record(cfg)
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


def station_uses_serial_scanner(st: StationConfig) -> bool:
    return bool(st.scanner_serial_port and st.scanner_serial_port.strip())


def _camera_is_serial_peer_record_feed(
    stations: list[StationConfig], camera_index: int
) -> bool:
    """Camera này đang là camera ghi của ít nhất một quầy dùng máy quét COM."""
    return any(
        station_uses_serial_scanner(s) and s.record_camera_index == camera_index
        for s in stations[:2]
    )


def station_for_decode_camera(
    stations: list[StationConfig], camera_index: int
) -> StationConfig | None:
    for s in stations:
        if station_uses_serial_scanner(s):
            continue
        if s.decode_camera_index != camera_index:
            continue
        if _camera_is_serial_peer_record_feed(stations, camera_index):
            continue
        return s
    return None


def camera_should_decode_on_index(stations: list[StationConfig], camera_index: int) -> bool:
    """Có bật pyzbar trên camera_index không (đồng bộ với station_for_decode_camera)."""
    return station_for_decode_camera(stations, camera_index) is not None


def stations_non_serial_decode_collision(stations: list[StationConfig]) -> bool:
    """True nếu ≥2 quầy không dùng COM và cùng decode_camera_index (station_for_decode_camera chỉ khớp quầy đầu)."""
    dec: list[int] = []
    for s in stations[:2]:
        if station_uses_serial_scanner(s):
            continue
        dec.append(int(s.decode_camera_index))
    return len(dec) >= 2 and dec[0] == dec[1]
