from packrecorder.order_state import SAME_ORDER_GRACE_S, OrderStateMachine


def test_idle_to_recording():
    sm = OrderStateMachine()
    r = sm.on_scan("A", is_shutdown_countdown=False)
    assert r.should_start_recording
    assert r.new_active_order == "A"
    assert r.sound_immediate is None


def test_stop_same_order_plays_double_without_mark():
    """Chưa mark_recording_started → không áp dụng cửa sổ 10s (vd. test / tương thích)."""
    sm = OrderStateMachine()
    sm.on_scan("A", is_shutdown_countdown=False)
    r = sm.on_scan("A", is_shutdown_countdown=False, same_scan_stops_recording=True)
    assert r.should_stop_recording
    assert r.sound_immediate == "stop_double"


def test_same_code_grace_ignored_when_serial_off():
    sm = OrderStateMachine()
    sm.on_scan("A", is_shutdown_countdown=False)
    sm.mark_recording_started(100.0)
    r = sm.on_scan(
        "A",
        is_shutdown_countdown=False,
        same_scan_stops_recording=False,
        now_mono=100.5,
    )
    assert not r.should_stop_recording


def test_same_code_within_grace_no_stop():
    sm = OrderStateMachine()
    sm.on_scan("A", is_shutdown_countdown=False)
    sm.mark_recording_started(100.0)
    r = sm.on_scan(
        "A",
        is_shutdown_countdown=False,
        same_scan_stops_recording=True,
        now_mono=100.0 + SAME_ORDER_GRACE_S - 0.5,
    )
    assert not r.should_stop_recording


def test_same_code_after_grace_stops():
    sm = OrderStateMachine()
    sm.on_scan("A", is_shutdown_countdown=False)
    sm.mark_recording_started(100.0)
    r = sm.on_scan(
        "A",
        is_shutdown_countdown=False,
        same_scan_stops_recording=True,
        now_mono=100.0 + SAME_ORDER_GRACE_S + 0.5,
    )
    assert r.should_stop_recording
    assert r.sound_immediate == "stop_double"


def test_switch_orders_when_camera_mode_same_code_ignored():
    sm = OrderStateMachine()
    sm.on_scan("A", is_shutdown_countdown=False, same_scan_stops_recording=False)
    sm.on_scan(
        "A",
        is_shutdown_countdown=False,
        same_scan_stops_recording=False,
    )
    r1 = sm.on_scan(
        "B",
        is_shutdown_countdown=False,
        same_scan_stops_recording=False,
    )
    assert r1.should_stop_recording
    r2 = sm.notify_stop_confirmed()
    assert r2.should_start_recording and r2.new_active_order == "B"


def test_switch_orders_sequence():
    sm = OrderStateMachine()
    sm.on_scan("A", is_shutdown_countdown=False)
    r1 = sm.on_scan("B", is_shutdown_countdown=False)
    assert r1.should_stop_recording and r1.sound_immediate is None
    r2 = sm.notify_stop_confirmed()
    assert r2.should_start_recording and r2.new_active_order == "B"
    assert r2.sound_immediate is None


def test_shutdown_countdown():
    sm = OrderStateMachine()
    assert sm.on_scan("X", is_shutdown_countdown=True).consume_for_shutdown_cancel is True


def test_different_order_stops_even_within_grace():
    sm = OrderStateMachine()
    sm.on_scan("A", is_shutdown_countdown=False)
    sm.mark_recording_started(100.0)
    r = sm.on_scan(
        "B",
        is_shutdown_countdown=False,
        same_scan_stops_recording=True,
        now_mono=100.5,
    )
    assert r.should_stop_recording
