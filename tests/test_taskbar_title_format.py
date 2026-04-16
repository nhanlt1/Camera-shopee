from packrecorder.ui.window_title_summary import format_minimized_window_title


def test_short_title_starts_with_pack_recorder() -> None:
    t = format_minimized_window_title("Máy 1: Chờ", "Máy 2: Chờ")
    assert t.startswith("Pack Recorder —")


def test_empty_fallback() -> None:
    assert format_minimized_window_title("", "") == "Pack Recorder"
