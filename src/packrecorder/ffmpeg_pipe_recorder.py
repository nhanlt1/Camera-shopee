from __future__ import annotations

import subprocess
import sys
from pathlib import Path
from queue import Empty, Full, Queue
from threading import Thread
from typing import Optional

from packrecorder.ffmpeg_encoders import ffmpeg_lists_encoder
from packrecorder.subprocess_win import popen_extra_kwargs
from packrecorder.windows_job import assign_process_to_job_object


class FFmpegPipeRecorder:
    def __init__(
        self,
        ffmpeg_exe: Path,
        width: int,
        height: int,
        fps: int,
        *,
        codec_preference: str = "auto",
        bitrate_kbps: int = 3000,
        h264_crf: int = 26,
        attach_job: bool = True,
        frame_queue_size: int = 6,
        drop_frames_when_full: bool = True,
    ) -> None:
        self._ffmpeg = ffmpeg_exe
        self._w, self._h, self._fps = width, height, fps
        self._codec_pref = (codec_preference or "auto").strip().lower()
        self._bitrate_kbps = max(400, min(50000, int(bitrate_kbps)))
        self._h264_crf = max(18, min(35, int(h264_crf)))
        self._attach_job = attach_job
        self._proc: Optional[subprocess.Popen[bytes]] = None
        self._frame_queue_size = max(2, int(frame_queue_size))
        self._drop_frames_when_full = drop_frames_when_full
        self._frame_q: Queue[bytes | None] | None = None
        self._writer_thread: Thread | None = None

    def _use_hevc_encoder(self) -> bool:
        pref = self._codec_pref
        if pref in ("h264", "avc", "x264"):
            return False
        has = ffmpeg_lists_encoder(self._ffmpeg, "libx265")
        if pref in ("hevc", "h265", "x265"):
            return has
        return has

    def _video_args(self, output_mp4: Path) -> list[str]:
        br = self._bitrate_kbps
        bufsize = min(50000, br * 2)
        if self._use_hevc_encoder():
            return [
                "-an",
                "-c:v",
                "libx265",
                "-tag:v",
                "hvc1",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                "-b:v",
                f"{br}k",
                "-maxrate",
                f"{br}k",
                "-bufsize",
                f"{bufsize}k",
                "-x265-params",
                "log-level=error",
                "-movflags",
                "+faststart",
                str(output_mp4),
            ]
        return [
            "-an",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-tune",
            "zerolatency",
            "-crf",
            str(self._h264_crf),
            "-profile:v",
            "main",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output_mp4),
        ]

    def _writer_loop(self) -> None:
        assert self._frame_q is not None
        assert self._proc is not None
        stdin = self._proc.stdin
        if stdin is None:
            return
        while True:
            item = self._frame_q.get()
            if item is None:
                break
            try:
                stdin.write(item)
            except BrokenPipeError:
                break
            except ValueError:
                break

    def start(self, output_mp4: Path) -> None:
        output_mp4.parent.mkdir(parents=True, exist_ok=True)
        cmd: list[str] = [
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
            cmd.extend(["-vf", "scale=trunc(iw/2)*2:trunc(ih/2)*2"])
        cmd.extend(self._video_args(output_mp4))
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            **popen_extra_kwargs(),
        )
        if (
            self._attach_job
            and self._proc.pid
            and sys.platform == "win32"
        ):
            assign_process_to_job_object(self._proc.pid)
        self._frame_q = Queue(maxsize=self._frame_queue_size)
        self._writer_thread = Thread(target=self._writer_loop, daemon=True)
        self._writer_thread.start()

    def write_frame(self, bgr_bytes: bytes) -> None:
        if not self._frame_q or not self._proc:
            return
        if self._drop_frames_when_full:
            try:
                self._frame_q.put_nowait(bgr_bytes)
            except Full:
                try:
                    _ = self._frame_q.get_nowait()
                except Empty:
                    pass
                try:
                    self._frame_q.put_nowait(bgr_bytes)
                except Full:
                    pass
        else:
            self._frame_q.put(bgr_bytes)

    def stop(self, timeout: float = 15.0) -> None:
        if self._frame_q is not None and self._writer_thread is not None:
            while True:
                try:
                    self._frame_q.get_nowait()
                except Empty:
                    break
            self._frame_q.put(None)
            self._writer_thread.join(timeout=5.0)
            self._writer_thread = None
        self._frame_q = None
        if not self._proc:
            return
        if self._proc.stdin:
            try:
                self._proc.stdin.close()
            except Exception:
                pass
        self._proc.wait(timeout=timeout)
        self._proc = None
