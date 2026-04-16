from __future__ import annotations

import sys
from pathlib import Path


def app_logo_candidates() -> list[Path]:
    """
    Đường dẫn logo ưu tiên cho cả dev và bản PyInstaller.

    - frozen: file nằm cạnh exe hoặc trong bundle (_MEIPASS) nếu đóng gói kèm.
    - dev: logo ở root repo.
    """
    out: list[Path] = []
    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        internal = exe_dir / "_internal"
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            base = Path(str(meipass))
            out.extend(
                [
                    base / "logo.ico",
                    base / "logo.jpg",
                    base / "resources" / "logo.ico",
                    base / "resources" / "logo.jpg",
                ]
            )
        out.extend(
            [
                internal / "logo.ico",
                internal / "logo.jpg",
                exe_dir / "logo.ico",
                exe_dir / "logo.jpg",
            ]
        )
        return out
    repo_root = Path(__file__).resolve().parents[2]
    return [
        repo_root / "logo.ico",
        repo_root / "logo.jpg",
    ]


def first_existing_logo_path() -> Path | None:
    for p in app_logo_candidates():
        if p.is_file():
            return p
    return None


def load_application_qicon():
    """
    Tải icon ứng dụng; Windows đôi khi từ chối QIcon(path) với JPG — thử QPixmap.
    """
    from PySide6.QtGui import QIcon, QPixmap

    path = first_existing_logo_path()
    if path is None:
        return None
    s = str(path)
    icon = QIcon(s)
    if not icon.isNull():
        return icon
    pix = QPixmap(s)
    if pix.isNull():
        return None
    return QIcon(pix)
