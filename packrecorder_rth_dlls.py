# PyInstaller runtime hook — chay truoc bat ky import numpy/cv2/Qt nao.
# Onefile: DLL trong numpy.libs can os.add_dll_directory + PATH, neu khong loi
# "Importing the numpy C-extensions failed".

from __future__ import annotations

import os
import sys


def _prepend_dll_search_paths() -> None:
    if not getattr(sys, "frozen", False):
        return
    base = getattr(sys, "_MEIPASS", None)
    if not base or not os.path.isdir(base):
        return

    candidates = [
        base,
        os.path.join(base, "numpy.libs"),
        os.path.join(base, "pyzbar"),
        os.path.join(base, "cv2"),
        os.path.join(base, "PySide6"),
        os.path.join(base, "shiboken6"),
        os.path.join(base, "PySide6", "plugins"),
        os.path.join(base, "PySide6", "plugins", "platforms"),
    ]
    extra = [p for p in candidates if os.path.isdir(p)]
    if not extra:
        return

    path_env = os.environ.get("PATH", "")
    prefix = os.pathsep.join(extra)
    os.environ["PATH"] = prefix + (os.pathsep + path_env if path_env else "")

    add = getattr(os, "add_dll_directory", None)
    if add:
        for p in extra:
            try:
                add(p)
            except OSError:
                pass


_prepend_dll_search_paths()
