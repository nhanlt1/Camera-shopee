from packrecorder.heartbeat_consumer import office_heartbeat_state


def test_green_when_fresh() -> None:
    light, msg, search_stale = office_heartbeat_state(60.0, fresh_s=120, stale_s=300)
    assert light == "green"
    assert "đồng bộ" in msg.lower() or "Đồng bộ" in msg


def test_red_when_stale() -> None:
    light, msg, search_stale = office_heartbeat_state(400.0, fresh_s=120, stale_s=300)
    assert light == "red"
    assert search_stale is True
    assert "CẢNH BÁO" in msg or "mất kết nối" in msg.lower()
    assert "phút" in msg


def test_yellow_contains_disconnect_minutes() -> None:
    light, msg, search_stale = office_heartbeat_state(180.0, fresh_s=120, stale_s=300)
    assert light == "yellow"
    assert search_stale is False
    assert "phút" in msg
