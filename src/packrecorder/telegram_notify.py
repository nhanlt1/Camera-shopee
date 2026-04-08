from __future__ import annotations

import os
import threading
import urllib.parse
import urllib.request


def _send_message_sync(text: str) -> None:
    token = (os.environ.get("PACKRECORDER_TELEGRAM_BOT_TOKEN") or "").strip()
    chat_id = (os.environ.get("PACKRECORDER_TELEGRAM_CHAT_ID") or "").strip()
    if not token or not chat_id:
        return
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = urllib.parse.urlencode({"chat_id": chat_id, "text": text}).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    with urllib.request.urlopen(req, timeout=3.0):
        pass


def send_duplicate_order_notice(order_id: str, packer: str) -> None:
    """Best-effort async Telegram notice for duplicate order scans."""
    text = (
        "Pack Recorder - Trùng đơn\n"
        f"Don: {order_id}\n"
        f"May: {packer}\n"
        "Da bo qua ghi moi (video da ton tai)."
    )

    def _runner() -> None:
        try:
            _send_message_sync(text)
        except Exception:
            return

    threading.Thread(target=_runner, daemon=True).start()

