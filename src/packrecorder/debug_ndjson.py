"""NDJSON debug lines for agent session (do not log secrets / full URLs with passwords)."""

from __future__ import annotations

import json
import time
from pathlib import Path

_SESSION = "91033f"
_LOG_NAME = f"debug-{_SESSION}.log"


def _log_path() -> Path:
    here = Path(__file__).resolve().parent
    for p in [here, *here.parents]:
        if (p / "pyproject.toml").is_file():
            return p / _LOG_NAME
    return here.parents[3] / _LOG_NAME


def dbg(hypothesis_id: str, location: str, message: str, **data: object) -> None:
    # region agent log
    try:
        payload = {
            "sessionId": _SESSION,
            "hypothesisId": hypothesis_id,
            "location": location,
            "message": message,
            "data": data,
            "timestamp": int(time.time() * 1000),
        }
        path = _log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass
    # endregion agent log


def dbg_safe_url(hypothesis_id: str, location: str, url: str) -> None:
    """Chỉ ghi scheme + host + path ngắn, không ghi user:pass."""
    u = (url or "").strip()
    if not u:
        dbg(hypothesis_id, location, "rtsp_url_empty", url_len=0)
        return
    try:
        from urllib.parse import urlparse

        pr = urlparse(u)
        host = pr.hostname or "?"
        dbg(
            hypothesis_id,
            location,
            "rtsp_url_shape",
            scheme=pr.scheme,
            host=host,
            port=pr.port,
            path_len=len(pr.path or ""),
        )
    except Exception:
        dbg(hypothesis_id, location, "rtsp_url_parse_fail", url_len=len(u))
