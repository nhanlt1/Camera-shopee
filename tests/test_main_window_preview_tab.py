from packrecorder.ui.preview_tab_policy import should_paint_quay_preview


def test_paint_only_on_counter_tab_for_stations() -> None:
    assert should_paint_quay_preview(
        multi_camera_mode="stations",
        main_tab_index=0,
        counter_tab_index=0,
    )
    assert not should_paint_quay_preview(
        multi_camera_mode="stations",
        main_tab_index=1,
        counter_tab_index=0,
    )


def test_non_stations_always_paints() -> None:
    assert should_paint_quay_preview(
        multi_camera_mode="pip",
        main_tab_index=1,
        counter_tab_index=0,
    )
