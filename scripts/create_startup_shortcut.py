"""Tạo lối tắt Pack Recorder trong thư mục Startup của Windows (shell:Startup)."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


def create_startup_shortcut(target_exe: Path, name: str = "Pack Recorder") -> Path:
    """
    Tạo file .lnk trỏ tới target_exe (thường là python.exe hoặc packrecorder.exe).
    Trả về đường dẫn file .lnk đã tạo.
    """
    startup = (
        Path(os.environ.get("APPDATA", ""))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / "Startup"
    )
    startup.mkdir(parents=True, exist_ok=True)
    lnk = startup / f"{name}.lnk"
    target_exe = target_exe.resolve()
    work_dir = str(target_exe.parent)
    ps = (
        f'$s=(New-Object -ComObject WScript.Shell).CreateShortcut({str(lnk)!r});'
        f'$s.TargetPath={str(target_exe)!r};'
        f'$s.WorkingDirectory={work_dir!r};'
        f'$s.Save()'
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        check=True,
    )
    return lnk


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: create_startup_shortcut.py <path-to-exe>", file=sys.stderr)
        return 2
    p = Path(sys.argv[1])
    out = create_startup_shortcut(p)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
