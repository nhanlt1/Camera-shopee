"""Optional: lower OS priority so foreground apps stay responsive."""

from __future__ import annotations

import os
import sys


def set_current_process_below_normal() -> bool:
    if sys.platform == "win32":
        try:
            import psutil

            p = psutil.Process(os.getpid())
            p.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
            return True
        except Exception:
            return False
    try:
        os.nice(5)
        return True
    except Exception:
        return False
