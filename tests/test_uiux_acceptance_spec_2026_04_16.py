from packrecorder.ui.main_window import MainWindow


def test_overlay_line_pair_method_exists():
    assert hasattr(MainWindow, "_mini_overlay_line_pair")


def test_escape_fullscreen_handler_exists():
    assert hasattr(MainWindow, "keyPressEvent")
