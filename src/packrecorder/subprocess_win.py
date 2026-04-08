"""Windows: kwargs for subprocess to avoid flashing console windows."""

from __future__ import annotations

import subprocess
import sys
from typing import Any


def popen_extra_kwargs() -> dict[str, Any]:
    """Windows: avoid console window when spawning ffmpeg/tools."""
    if sys.platform != "win32":
        return {}
    cf = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if not cf:
        return {}
    return {"creationflags": cf}


def run_extra_kwargs() -> dict[str, Any]:
    return popen_extra_kwargs()
