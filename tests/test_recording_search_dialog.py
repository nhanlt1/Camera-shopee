from packrecorder.ui.recording_search_dialog import (
    RecordingSearchPanel,
    _format_created_at_display,
)


def test_recording_search_panel_import() -> None:
    assert RecordingSearchPanel is not None


def test_format_created_at_display_iso() -> None:
    assert _format_created_at_display("2026-04-08T12:30:00") == "08/04/2026  12:30"


def test_format_created_at_display_empty() -> None:
    assert _format_created_at_display("") == ""
