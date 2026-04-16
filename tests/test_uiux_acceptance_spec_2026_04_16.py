from packrecorder.ui.main_window import MainWindow


def test_overlay_line_pair_method_exists():
    assert hasattr(MainWindow, "_mini_overlay_line_pair")


def test_escape_fullscreen_handler_exists():
    assert hasattr(MainWindow, "keyPressEvent")


def test_footer_control_handlers_exist():
    assert hasattr(MainWindow, "_on_retention_controls_changed")
    assert hasattr(MainWindow, "_on_shutdown_footer_toggled")
    assert hasattr(MainWindow, "_on_shutdown_time_changed")


def test_dashboard_tab_fetch_handlers_exist():
    assert hasattr(MainWindow, "_dashboard_fetch_rows")
    assert hasattr(MainWindow, "_dashboard_fetch_packers")


def test_dashboard_quick_range_handler_exists():
    from packrecorder.ui.dashboard_tab import DashboardTab

    assert hasattr(DashboardTab, "_on_quick_range_changed")
