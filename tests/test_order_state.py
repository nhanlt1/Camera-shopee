from packrecorder.order_state import OrderStateMachine


def test_idle_to_recording():
    sm = OrderStateMachine()
    r = sm.on_scan("A", is_shutdown_countdown=False)
    assert r.should_start_recording and r.should_check_duplicate
    assert r.new_active_order == "A"
    assert r.sound_immediate is None


def test_stop_same_order_plays_double():
    sm = OrderStateMachine()
    sm.on_scan("A", is_shutdown_countdown=False)
    r = sm.on_scan("A", is_shutdown_countdown=False)
    assert r.should_stop_recording
    assert r.sound_immediate == "stop_double"


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
