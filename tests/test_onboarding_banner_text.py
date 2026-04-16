from packrecorder.config import AppConfig, StationConfig
from packrecorder.ui.onboarding_banner import dual_station_banner_hint


def test_no_banner_when_onboarding_done():
    cfg = AppConfig()
    cfg.onboarding_complete = True
    cfg.stations = [StationConfig("a", "Máy 1", 0, 0)]
    assert dual_station_banner_hint(cfg, col=0) is None


def test_step1_when_com_empty():
    cfg = AppConfig()
    cfg.onboarding_complete = False
    cfg.first_run_setup_required = True
    cfg.stations = [StationConfig("a", "Máy 1", 0, 0)]
    cfg.stations[0].scanner_serial_port = ""
    cfg.stations[0].scanner_input_kind = "com"
    h = dual_station_banner_hint(cfg, col=0)
    assert h is not None
    assert "Bước 1" in h
