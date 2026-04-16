from __future__ import annotations


def should_paint_quay_preview(
    *,
    multi_camera_mode: str,
    main_tab_index: int,
    counter_tab_index: int,
) -> bool:
    if multi_camera_mode != "stations":
        return True
    return main_tab_index == counter_tab_index
