from packrecorder.order_state import OrderStateMachine


def test_cooldown_ignores_second_scan() -> None:
    sm = OrderStateMachine(transition_cooldown_s=1.0)
    t0 = 1000.0
    r1 = sm.on_scan(
        "A",
        is_shutdown_countdown=False,
        same_scan_stops_recording=True,
        now_mono=t0,
    )
    assert r1.should_start_recording
    r2 = sm.on_scan(
        "A",
        is_shutdown_countdown=False,
        same_scan_stops_recording=True,
        now_mono=t0 + 0.1,
    )
    assert not r2.should_stop_recording and not r2.should_start_recording
