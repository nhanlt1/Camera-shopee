from packrecorder.config import AppConfig
from packrecorder.feedback_sound import FeedbackPlayer


def test_duplicate_alert_uses_long_beep(monkeypatch):
    p = FeedbackPlayer(AppConfig())
    called = {"n": 0}

    def fake_long():
        called["n"] += 1

    monkeypatch.setattr(p, "play_long", fake_long)
    p.play_duplicate_order_alert()
    assert called["n"] == 1


def test_record_start_failed_alert_uses_long_beep(monkeypatch):
    p = FeedbackPlayer(AppConfig())
    called = {"n": 0}

    def fake_long():
        called["n"] += 1

    monkeypatch.setattr(p, "play_long", fake_long)
    p.play_record_start_failed_alert()
    assert called["n"] == 1


def test_play_quad_uses_long_beep(monkeypatch):
    p = FeedbackPlayer(AppConfig())
    called = {"n": 0}

    def fake_long():
        called["n"] += 1

    monkeypatch.setattr(p, "play_long", fake_long)
    p.play_quad()
    assert called["n"] == 1
