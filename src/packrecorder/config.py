from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

from packrecorder.record_resolution import normalize_record_resolution_preset

ScannerInputKind = Literal["com", "hid_pos", "keyboard", "camera"]
from packrecorder.record_roi import clamp_norm_rect

SoundMode = Literal["speaker", "scanner_host"]
MultiCameraMode = Literal["single", "stations", "pip"]
RecordVideoCodec = Literal["auto", "hevc", "h264"]
RecordCameraKind = Literal["usb", "rtsp"]

# Camera IP RTSP (Đa quầy): id logic 10 = quầy 0, 11 = quầy 1 — không trùng index USB 0–9.
STATION_RTSP_LOGICAL_ID_BASE = 10

# Mã cấu hình chế độ máy quét Winson (quét vào thiết bị — có dấu chấm cuối). Spec 2026-04-16 §7.6
WINSON_MODE_USB_COM = "881001133."
WINSON_MODE_USB_HID = "881001131."
WINSON_MODE_USB_KEYBOARD = "881001124."


@dataclass
class StationConfig:
    station_id: str
    packer_label: str = "Máy 1"
    record_camera_index: int = 0
    decode_camera_index: int = 0
    # usb: dùng record_camera_index 0–9. rtsp: URL đầy đủ; id logic ghi/ghi preview là 10/11.
    record_camera_kind: RecordCameraKind = "usb"
    record_rtsp_url: str = ""
    # Máy quét mã USB dạng serial (COM). Rỗng = đọc mã bằng camera + pyzbar.
    scanner_serial_port: str = ""
    scanner_serial_baud: int = 9600
    # VID/PID mong muốn để tự nhận diện cổng COM đúng máy quét.
    # Chuỗi HEX 4 ký tự (vd: "0C2E", "0B61"), rỗng = không ép.
    scanner_usb_vid: str = ""
    scanner_usb_pid: str = ""
    # com = USB–serial (COM); hid_pos = HID POS qua hidapi (VID/PID), không dùng COM.
    scanner_input_kind: ScannerInputKind = "com"
    # -1 = xem trước trùng camera ghi quầy này; >=0 = index camera xem trước.
    preview_display_index: int = -1
    # Danh sách camera USB xem thêm cho màn 1 quầy (không dùng để decode/ghi).
    extra_preview_usb_indices: list[int] = field(default_factory=list)
    # Màn 1 quầy: focus = một camera lớn, grid = hiển thị lưới thumbnail.
    single_station_view_mode: Literal["focus", "grid"] = "focus"
    # Camera USB đang được focus; None = camera ghi của quầy.
    focused_preview_usb_index: int | None = None
    # (x, y, w, h) chuẩn hoá 0..1 theo khung camera ghi; None = toàn khung.
    record_roi_norm: tuple[float, float, float, float] | None = None
    # Mini overlay (theo từng máy): bật/tắt từng phần hiển thị trên dòng trạng thái.
    mini_overlay_show_label: bool = True
    mini_overlay_show_state: bool = True
    mini_overlay_show_order: bool = True
    mini_overlay_show_current_time: bool = True
    mini_overlay_show_packing_duration: bool = True


def default_stations() -> list[StationConfig]:
    return [
        StationConfig(str(uuid.uuid4()), "Máy 1", 0, 0),
        StationConfig(str(uuid.uuid4()), "Máy 2", 1, 1),
    ]


def default_machine_id() -> str:
    try:
        return f"machine-{uuid.getnode():012x}"
    except Exception:
        return f"machine-{uuid.uuid4().hex[:12]}"


def _normalize_record_camera_kind(value: object) -> RecordCameraKind:
    v = str(value or "").strip().lower()
    return "rtsp" if v == "rtsp" else "usb"


def is_rtsp_stream_url(url: object) -> bool:
    """Chỉ coi là luồng RTSP khi URL đúng scheme — tránh gọi FFmpeg/OpenCV RTSP với USB hoặc chuỗi lạ."""
    s = (url or "").strip().lower()
    return s.startswith("rtsp://") or s.startswith("rtsps://")


def station_record_cam_id(st: StationConfig, station_index: int) -> int:
    if st.record_camera_kind == "rtsp" and is_rtsp_stream_url(st.record_rtsp_url):
        return STATION_RTSP_LOGICAL_ID_BASE + int(station_index)
    return int(st.record_camera_index)


@dataclass
class AppConfig:
    schema_version: int = 10
    video_root: str = ""
    camera_index: int = 0
    packer_label: str = "Máy 1"
    ffmpeg_path: str = ""
    # Mặc định tắt: tránh đến giờ hẹn app bật đếm ngược rồi gọi tắt Windows (dễ tưởng app tự thoát).
    shutdown_enabled: bool = False
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
    # native | vga | hd | full_hd — mặc định HD 720p cho cân bằng chất lượng / hiệu năng.
    record_resolution: str = "hd"
    # FPS đích khi ghi file (đồng bộ ffmpeg -r và nhịp đẩy khung).
    record_fps: int = 30
    # auto: HEVC nếu FFmpeg có libx265, không thì H.264; h264 mặc định — ít tải CPU khi quay realtime.
    record_video_codec: RecordVideoCodec = "h264"
    # libx264 realtime: CRF 25–28 tiết kiệm dung lượng, ultrafast trong FFmpegPipeRecorder.
    record_h264_crf: int = 26
    # libx265 (auto/hevc): giữ bitrate khi không dùng CRF.
    record_video_bitrate_kbps: int = 3000
    # pyzbar: quét 1 / N khung (15 ≈ 2 Hz @30fps). Giảm CPU; tăng nếu bỏ sót mã.
    barcode_scan_interval_frames: int = 15
    # Thu nhỏ ảnh trước khi pyzbar (0.5 = 50% kích thước mỗi cạnh).
    barcode_scan_scale: float = 0.5
    # Cửa sổ luôn trên cùng (giúp thấy app; với máy quét kiểu bàn phím nên kèm focus ô mã).
    window_always_on_top: bool = True
    # Khay hệ thống / chạy nền (plan 2026-04-07)
    minimize_to_tray: bool = False
    start_in_tray: bool = False
    close_to_tray: bool = True
    low_process_priority: bool = False
    tray_show_toast_on_order: bool = True
    tray_health_beep_interval_min: int = 0
    tray_health_beep_volume: float = 0.12
    enable_global_barcode_hook: bool = False
    # COM-only: không dùng đường nhập kiểu wedge (Enter trong ô Mã đơn).
    scanner_com_only: bool = True
    # 0 = tắt. Sau mỗi lần chuyển trạng thái ghi (on_scan), bỏ qua tín hiệu quét trùng trong cửa sổ này (giảm race COM/camera).
    order_transition_cooldown_s: float = 0.0
    # 0 = tắt. MP capture/scanner: nếu wall-clock heartbeat cũ hơn N giây → restart pipeline (xem MainWindow watchdog).
    ipc_worker_stale_seconds: float = 0.0
    # Capture + pyzbar trong multiprocessing + SharedMemory (Windows spawn); luôn bật — không tùy chọn UI.
    use_multiprocessing_camera_pipeline: bool = True
    # HA / heartbeat / tìm kiếm (plan 2026-04-08)
    video_backup_root: str = ""
    status_json_relative: str = "PackRecorder/status.json"
    heartbeat_interval_ms: int = 60_000
    heartbeat_fresh_seconds: int = 120
    heartbeat_stale_seconds: int = 300
    sync_worker_interval_ms: int = 300_000
    remote_status_json_path: str = ""
    office_heartbeat_poll_ms: int = 30_000
    disk_warn_percent: float = 80.0
    disk_critical_percent: float = 90.0
    video_retention_keep_days: int = 16
    # UI simplification / kiosk / wizard (spec 2026-04-16)
    first_run_setup_required: bool = True
    onboarding_complete: bool = False
    default_to_kiosk: bool = True
    kiosk_fullscreen_on_start: bool = False
    mini_overlay_enabled: bool = True
    mini_overlay_click_through: bool = False
    mini_overlay_corner: str = "bottom_right"
    windows_startup_hint_shown: bool = False
    # Dashboard đa máy: dữ liệu thống kê dùng SQLite chia sẻ trên Drive.
    software_id: str = "default"
    machine_id: str = field(default_factory=default_machine_id)
    analytics_shared_root_relative: str = "PackRecorder/analytics"


def _station_from_dict(d: dict[str, Any]) -> StationConfig:
    known = {f.name for f in StationConfig.__dataclass_fields__.values()}
    kw = {k: v for k, v in d.items() if k in known}
    if "station_id" not in kw or not kw["station_id"]:
        kw["station_id"] = str(uuid.uuid4())
    r = kw.get("record_roi_norm")
    if r is not None and isinstance(r, list) and len(r) == 4:
        kw["record_roi_norm"] = tuple(float(r[i]) for i in range(4))
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


def ensure_stations_layout(cfg: AppConfig) -> None:
    """Chế độ đa quầy: giữ 1–2 quầy theo cấu hình; tối thiểu 1; không tự thêm quầy thứ hai."""
    if cfg.multi_camera_mode != "stations":
        return
    if not cfg.stations:
        cfg.stations = [StationConfig(str(uuid.uuid4()), "Máy 1", 0, 0)]
    elif len(cfg.stations) > 2:
        cfg.stations[:] = cfg.stations[:2]


def ensure_dual_stations(cfg: AppConfig) -> None:
    """Đủ đúng 2 quầy (wizard «Hai quầy» hoặc migrate)."""
    if cfg.multi_camera_mode != "stations":
        return
    ensure_stations_layout(cfg)
    while len(cfg.stations) < 2:
        n = len(cfg.stations)
        cfg.stations.append(
            StationConfig(str(uuid.uuid4()), f"Máy {n + 1}", min(n, 9), min(n, 9))
        )


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
            if station_uses_dedicated_barcode_scanner(st):
                continue
            other = cfg.stations[1 - i]
            other_rec = station_record_cam_id(other, 1 - i)
            if st.decode_camera_index == other_rec:
                cfg.stations[i] = replace(
                    st, decode_camera_index=station_record_cam_id(st, i)
                )
                changed = True
        if not changed:
            break


def ensure_distinct_station_record_cameras(cfg: AppConfig) -> None:
    """Hai quầy không dùng chung một camera ghi (tránh một webcam hiện ở cả hai cột)."""
    if cfg.multi_camera_mode != "stations" or len(cfg.stations) < 2:
        return
    s0, s1 = cfg.stations[0], cfg.stations[1]
    if (
        s0.record_camera_kind == "rtsp"
        and s1.record_camera_kind == "rtsp"
        and is_rtsp_stream_url(s0.record_rtsp_url)
        and is_rtsp_stream_url(s1.record_rtsp_url)
        and (s0.record_rtsp_url or "").strip() == (s1.record_rtsp_url or "").strip()
    ):
        rid0 = station_record_cam_id(s0, 0)
        alt = next((i for i in range(10) if i != rid0), 1)
        cfg.stations[1] = replace(
            s1, record_camera_kind="usb", record_rtsp_url="", record_camera_index=alt
        )
        return
    id0 = station_record_cam_id(s0, 0)
    id1 = station_record_cam_id(s1, 1)
    if id0 != id1:
        return
    a = id0
    for alt in range(10):
        if alt != a:
            cfg.stations[1] = replace(s1, record_camera_index=alt)
            return


def normalize_record_video_codec(value: str) -> RecordVideoCodec:
    s = (value or "").strip().lower()
    if s in ("hevc", "h265", "x265"):
        return "hevc"
    if s in ("h264", "avc", "x264"):
        return "h264"
    if s == "auto":
        return "auto"
    return "auto"


def _normalize_scanner_input_kind(value: object) -> ScannerInputKind:
    s = str(value or "").strip().lower()
    if s == "hid_pos":
        return "hid_pos"
    if s in ("keyboard", "wedge"):
        return "keyboard"
    if s == "camera":
        return "camera"
    return "com"


def _normalize_usb_hex_id(value: object) -> str:
    raw = str(value or "").strip().upper()
    if raw.startswith("0X"):
        raw = raw[2:]
    if len(raw) != 4:
        return ""
    if not all(ch in "0123456789ABCDEF" for ch in raw):
        return ""
    return raw


def _normalize_preview_usb_indices(value: object) -> list[int]:
    out: list[int] = []
    raw = value if isinstance(value, list) else []
    for item in raw:
        try:
            idx = int(item)
        except (TypeError, ValueError):
            continue
        if 0 <= idx <= 9 and idx not in out:
            out.append(idx)
    return out[:8]


def normalize_config(cfg: AppConfig) -> AppConfig:
    if cfg.multi_camera_mode == "stations" and not cfg.stations:
        cfg.stations = default_stations()
    for i, s in enumerate(cfg.stations):
        kind = _normalize_record_camera_kind(s.record_camera_kind)
        url = (s.record_rtsp_url or "").strip()
        if kind == "rtsp" and not url:
            kind = "usb"
        elif kind == "rtsp" and not is_rtsp_stream_url(url):
            kind = "usb"
            url = ""
        if kind == "rtsp":
            rid = STATION_RTSP_LOGICAL_ID_BASE + i
            s = replace(
                s,
                record_camera_kind="rtsp",
                record_rtsp_url=url,
                record_camera_index=rid,
            )
            if not station_uses_dedicated_barcode_scanner(s):
                s = replace(s, decode_camera_index=rid)
        else:
            s = replace(s, record_camera_kind="usb", record_rtsp_url="")
            if s.record_camera_index < 0:
                s = replace(s, record_camera_index=0)
            elif s.record_camera_index > 9:
                s = replace(s, record_camera_index=9)
            if not station_uses_dedicated_barcode_scanner(s):
                s = replace(s, decode_camera_index=s.record_camera_index)
        if s.decode_camera_index < 0:
            s = replace(s, decode_camera_index=0)
        if s.record_camera_index < 0:
            s = replace(s, record_camera_index=0)
        if s.preview_display_index < -1 or s.preview_display_index > 99:
            s = replace(s, preview_display_index=-1)
        extra_preview = _normalize_preview_usb_indices(
            getattr(s, "extra_preview_usb_indices", [])
        )
        if s.preview_display_index >= 0 and s.preview_display_index <= 9:
            if s.preview_display_index not in extra_preview:
                extra_preview.insert(0, int(s.preview_display_index))
        rec_usb = int(s.record_camera_index)
        if rec_usb in extra_preview:
            extra_preview = [i for i in extra_preview if i != rec_usb]
        mode = str(getattr(s, "single_station_view_mode", "focus")).strip().lower()
        if mode not in ("focus", "grid"):
            mode = "focus"
        focus_raw = getattr(s, "focused_preview_usb_index", None)
        focus_idx: int | None
        if focus_raw is None:
            focus_idx = None
        else:
            try:
                v = int(focus_raw)
            except (TypeError, ValueError):
                focus_idx = None
            else:
                focus_idx = v if 0 <= v <= 9 else None
        if focus_idx is not None and focus_idx not in extra_preview and focus_idx != rec_usb:
            focus_idx = None
        s = replace(
            s,
            extra_preview_usb_indices=extra_preview,
            single_station_view_mode=mode,
            focused_preview_usb_index=focus_idx,
            mini_overlay_show_label=bool(getattr(s, "mini_overlay_show_label", True)),
            mini_overlay_show_state=bool(getattr(s, "mini_overlay_show_state", True)),
            mini_overlay_show_order=bool(getattr(s, "mini_overlay_show_order", True)),
            mini_overlay_show_current_time=bool(
                getattr(s, "mini_overlay_show_current_time", True)
            ),
            mini_overlay_show_packing_duration=bool(
                getattr(s, "mini_overlay_show_packing_duration", True)
            ),
        )
        roi = s.record_roi_norm
        if roi is not None:
            if isinstance(roi, (list, tuple)) and len(roi) == 4:
                x, y, w, h = (
                    float(roi[0]),
                    float(roi[1]),
                    float(roi[2]),
                    float(roi[3]),
                )
                s = replace(s, record_roi_norm=clamp_norm_rect(x, y, w, h))
            else:
                s = replace(s, record_roi_norm=None)
        if s.scanner_serial_baud < 1200 or s.scanner_serial_baud > 921600:
            s = replace(s, scanner_serial_baud=9600)
        vid = _normalize_usb_hex_id(s.scanner_usb_vid)
        pid = _normalize_usb_hex_id(s.scanner_usb_pid)
        sk = _normalize_scanner_input_kind(getattr(s, "scanner_input_kind", "com"))
        if sk == "hid_pos" and (not vid or not pid):
            sk = "com"
        if sk == "keyboard":
            s = replace(s, scanner_serial_port="")
            vid = ""
            pid = ""
        if sk == "camera":
            s = replace(s, scanner_serial_port="")
            vid = ""
            pid = ""
        s = replace(s, scanner_usb_vid=vid, scanner_usb_pid=pid, scanner_input_kind=sk)
        cfg.stations[i] = s
    ensure_distinct_station_record_cameras(cfg)
    ensure_decode_camera_not_peer_record(cfg)
    if cfg.pip_main_camera_index == cfg.pip_sub_camera_index:
        cfg.pip_sub_camera_index = min(9, cfg.pip_main_camera_index + 1)
    cfg.record_resolution = normalize_record_resolution_preset(cfg.record_resolution)
    if cfg.record_fps < 1:
        cfg.record_fps = 30
    elif cfg.record_fps > 60:
        cfg.record_fps = 60
    cfg.record_video_codec = normalize_record_video_codec(
        str(cfg.record_video_codec)
    )
    if cfg.record_video_bitrate_kbps < 400:
        cfg.record_video_bitrate_kbps = 400
    elif cfg.record_video_bitrate_kbps > 50000:
        cfg.record_video_bitrate_kbps = 50000
    if cfg.record_h264_crf < 18:
        cfg.record_h264_crf = 18
    elif cfg.record_h264_crf > 35:
        cfg.record_h264_crf = 35
    if cfg.barcode_scan_interval_frames < 1:
        cfg.barcode_scan_interval_frames = 1
    elif cfg.barcode_scan_interval_frames > 60:
        cfg.barcode_scan_interval_frames = 60
    s = float(cfg.barcode_scan_scale)
    if s < 0.25:
        cfg.barcode_scan_scale = 0.25
    elif s > 1.0:
        cfg.barcode_scan_scale = 1.0
    cfg.window_always_on_top = bool(cfg.window_always_on_top)
    cfg.minimize_to_tray = bool(cfg.minimize_to_tray)
    cfg.start_in_tray = bool(cfg.start_in_tray)
    if not cfg.minimize_to_tray:
        cfg.start_in_tray = False
    cfg.close_to_tray = bool(cfg.close_to_tray)
    cfg.low_process_priority = bool(cfg.low_process_priority)
    cfg.tray_show_toast_on_order = bool(cfg.tray_show_toast_on_order)
    # scanner_com_only: True => chỉ chấp nhận luồng quét chuyên dụng (COM/HID POS), tắt wedge.
    # False => cho phép wedge (gõ phím vào ô mã + Enter). Tự suy ra từ scanner_input_kind của các station.
    any_wedge_station = any(
        getattr(st, "scanner_input_kind", "com") == "keyboard" for st in cfg.stations
    )
    cfg.scanner_com_only = not any_wedge_station
    cfg.enable_global_barcode_hook = False
    oc = float(cfg.order_transition_cooldown_s)
    if oc < 0:
        cfg.order_transition_cooldown_s = 0.0
    elif oc > 30.0:
        cfg.order_transition_cooldown_s = 30.0
    iw = float(cfg.ipc_worker_stale_seconds)
    if iw < 0:
        cfg.ipc_worker_stale_seconds = 0.0
    elif iw > 120.0:
        cfg.ipc_worker_stale_seconds = 120.0
    if cfg.tray_health_beep_interval_min < 0:
        cfg.tray_health_beep_interval_min = 0
    elif cfg.tray_health_beep_interval_min > 1440:
        cfg.tray_health_beep_interval_min = 1440
    tv = float(cfg.tray_health_beep_volume)
    if tv < 0.0:
        cfg.tray_health_beep_volume = 0.0
    elif tv > 1.0:
        cfg.tray_health_beep_volume = 1.0
    else:
        cfg.tray_health_beep_volume = tv
    if cfg.heartbeat_interval_ms < 5_000:
        cfg.heartbeat_interval_ms = 5_000
    elif cfg.heartbeat_interval_ms > 3_600_000:
        cfg.heartbeat_interval_ms = 3_600_000
    if cfg.heartbeat_fresh_seconds < 30:
        cfg.heartbeat_fresh_seconds = 30
    if cfg.heartbeat_stale_seconds < cfg.heartbeat_fresh_seconds:
        cfg.heartbeat_stale_seconds = cfg.heartbeat_fresh_seconds + 60
    if cfg.sync_worker_interval_ms < 10_000:
        cfg.sync_worker_interval_ms = 10_000
    if cfg.office_heartbeat_poll_ms < 5_000:
        cfg.office_heartbeat_poll_ms = 5_000
    if cfg.disk_warn_percent < 50:
        cfg.disk_warn_percent = 50.0
    if cfg.disk_critical_percent < cfg.disk_warn_percent:
        cfg.disk_critical_percent = cfg.disk_warn_percent + 5.0
    if cfg.video_retention_keep_days < 0:
        cfg.video_retention_keep_days = 0
    elif cfg.video_retention_keep_days > 3650:
        cfg.video_retention_keep_days = 3650
    cfg.first_run_setup_required = bool(cfg.first_run_setup_required)
    cfg.onboarding_complete = bool(cfg.onboarding_complete)
    cfg.default_to_kiosk = bool(cfg.default_to_kiosk)
    cfg.kiosk_fullscreen_on_start = bool(cfg.kiosk_fullscreen_on_start)
    cfg.mini_overlay_enabled = bool(cfg.mini_overlay_enabled)
    cfg.mini_overlay_click_through = bool(cfg.mini_overlay_click_through)
    corner = str(cfg.mini_overlay_corner or "").strip().lower()
    cfg.mini_overlay_corner = (
        corner
        if corner in ("bottom_right", "bottom_left", "top_right", "top_left")
        else "bottom_right"
    )
    cfg.windows_startup_hint_shown = bool(cfg.windows_startup_hint_shown)
    sid = str(getattr(cfg, "software_id", "") or "").strip()
    cfg.software_id = sid or "default"
    mid = str(getattr(cfg, "machine_id", "") or "").strip()
    cfg.machine_id = mid or default_machine_id()
    analytics_root = str(getattr(cfg, "analytics_shared_root_relative", "") or "").strip()
    cfg.analytics_shared_root_relative = analytics_root or "PackRecorder/analytics"
    # File heartbeat / máy phụ đọc: cùng cây thư mục với thư mục gốc video (không cấu hình riêng).
    cfg.status_json_relative = "PackRecorder/status.json"
    vr_root = (cfg.video_root or "").strip()
    cfg.remote_status_json_path = (
        str(Path(vr_root) / cfg.status_json_relative) if vr_root else ""
    )
    cfg.use_multiprocessing_camera_pipeline = bool(
        cfg.use_multiprocessing_camera_pipeline
    )
    # Cho phép tắt MP (luồng process + shared memory) khi gặp crash native — không sửa config.json.
    _dmp = (os.environ.get("PACKRECORDER_DISABLE_MP") or "").strip().lower()
    if _dmp in ("1", "true", "yes", "on"):
        cfg.use_multiprocessing_camera_pipeline = False
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
    if cfg.schema_version < 3:
        cfg.schema_version = 3
    if cfg.schema_version < 4:
        cfg.schema_version = 4
    if cfg.schema_version < 5:
        cfg.schema_version = 5
    if cfg.schema_version < 6:
        cfg.schema_version = 6
    if cfg.schema_version < 7:
        cfg.schema_version = 7
    if cfg.schema_version < 8:
        cfg.schema_version = 8
    if cfg.schema_version < 9:
        # Cài đặt cũ: không bắt Wizard lần đầu sau khi nâng schema.
        cfg = replace(
            cfg,
            schema_version=9,
            onboarding_complete=True,
            first_run_setup_required=False,
        )
    if cfg.schema_version < 10:
        cfg = replace(cfg, schema_version=10)
    return normalize_config(cfg)


def default_config_path() -> Path:
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "PackRecorder" / "config.json"
    return Path.home() / ".packrecorder" / "config.json"


def station_uses_serial_scanner(st: StationConfig) -> bool:
    return bool(st.scanner_serial_port and st.scanner_serial_port.strip())


def station_uses_hid_pos_scanner(st: StationConfig) -> bool:
    """HID POS: cần VID+PID hợp lệ (sau normalize)."""
    if getattr(st, "scanner_input_kind", "com") != "hid_pos":
        return False
    return bool(_normalize_usb_hex_id(st.scanner_usb_vid)) and bool(
        _normalize_usb_hex_id(st.scanner_usb_pid)
    )


def station_uses_dedicated_barcode_scanner(st: StationConfig) -> bool:
    """Máy quét phần cứng (COM hoặc HID POS), không đọc mã bằng pyzbar trên camera."""
    return station_uses_serial_scanner(st) or station_uses_hid_pos_scanner(st)


def station_uses_keyboard_wedge(st: StationConfig) -> bool:
    """Máy quét gõ phím (HID keyboard wedge): nhập trực tiếp vào ô mã + Enter."""
    return getattr(st, "scanner_input_kind", "com") == "keyboard"


def station_uses_camera_decode(st: StationConfig) -> bool:
    """Đọc mã bằng camera ghi (pyzbar). Bao gồm cả cấu hình cũ: kind=com nhưng không có port."""
    kind = getattr(st, "scanner_input_kind", "com")
    if kind == "camera":
        return True
    if kind == "com" and not (st.scanner_serial_port or "").strip():
        return True
    return False


def _camera_is_serial_peer_record_feed(
    stations: list[StationConfig], camera_index: int
) -> bool:
    """Camera này đang là camera ghi của ít nhất một quầy dùng máy quét COM/HID (không pyzbar)."""
    return any(
        station_uses_dedicated_barcode_scanner(s)
        and station_record_cam_id(s, idx) == camera_index
        for idx, s in enumerate(stations[:2])
    )


def station_for_decode_camera(
    stations: list[StationConfig], camera_index: int
) -> StationConfig | None:
    for s in stations:
        if station_uses_dedicated_barcode_scanner(s):
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
    """True nếu ≥2 quầy không dùng máy quét COM/HID và cùng decode_camera_index (station_for_decode_camera chỉ khớp quầy đầu)."""
    dec: list[int] = []
    for s in stations[:2]:
        if station_uses_dedicated_barcode_scanner(s):
            continue
        dec.append(int(s.decode_camera_index))
    return len(dec) >= 2 and dec[0] == dec[1]
