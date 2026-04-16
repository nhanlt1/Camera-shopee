from packrecorder.ui.mini_status_overlay import line_style_stylesheet


def test_recording_style_includes_padding():
    css = line_style_stylesheet("recording")
    assert "padding:4px" in css.replace(" ", "")


def test_idle_and_error_distinct():
    assert line_style_stylesheet("idle") != line_style_stylesheet("error")
