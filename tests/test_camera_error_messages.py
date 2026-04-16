from packrecorder.ui.camera_error_messages import (
    mp_worker_error_dialog_buttons,
    mp_worker_error_dialog_text,
)


def test_three_button_labels():
    a, b, c = mp_worker_error_dialog_buttons()
    assert "Thử lại" in a
    assert "Thiết lập" in b
    assert "Đóng" in c


def test_mp_worker_error_contains_cam_index():
    assert "0" in mp_worker_error_dialog_text(0)
    assert "3" in mp_worker_error_dialog_text(3)
