from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from typing import Optional

from packrecorder.windows_job import assign_process_to_job_object


class FFmpegPipeRecorder:
    def __init__(
        self,
        ffmpeg_exe: Path,
        width: int,
        height: int,
        fps: int,
        *,
        attach_job: bool = True,
    ) -> None:
        self._ffmpeg = ffmpeg_exe
        self._w, self._h, self._fps = width, height, fps
        self._attach_job = attach_job
        self._proc: Optional[subprocess.Popen[bytes]] = None

    def start(self, output_mp4: Path) -> None:
        output_mp4.parent.mkdir(parents=True, exist_ok=True)
        # Mobile / Zalo: H.264 yuv420p + main profile; chẵn WxH; moov đầu file (faststart).
        cmd = [
            str(self._ffmpeg),
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{self._w}x{self._h}",
            "-r",
            str(self._fps),
            "-i",
            "-",
        ]
        if self._w % 2 or self._h % 2:
            cmd.extend(
                ["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"]
            )
        cmd.extend(
            [
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-tune",
                "zerolatency",
                "-profile:v",
                "main",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(output_mp4),
            ]
        )
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        if (
            self._attach_job
            and self._proc.pid
            and sys.platform == "win32"
        ):
            assign_process_to_job_object(self._proc.pid)

    def write_frame(self, bgr_bytes: bytes) -> None:
        if self._proc and self._proc.stdin:
            self._proc.stdin.write(bgr_bytes)

    def stop(self, timeout: float = 15.0) -> None:
        if not self._proc:
            return
        if self._proc.stdin:
            self._proc.stdin.close()
        self._proc.wait(timeout=timeout)
        self._proc = None
