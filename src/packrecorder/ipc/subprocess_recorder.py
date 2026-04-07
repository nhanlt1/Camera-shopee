"""Ghi video trong subprocess: dừng bằng Event + join Process."""

from __future__ import annotations

import multiprocessing as mp
from multiprocessing.queues import Queue
from queue import Empty
from typing import Any, Callable, Tuple


class SubprocessRecordingHandle:
    """Cùng API tối thiểu với FFmpegPipeRecorder.stop() cho main_window."""

    def __init__(self, stop_ev: Any, proc: mp.Process) -> None:
        self._stop = stop_ev
        self._proc = proc

    @staticmethod
    def start_encoder(
        ctx: mp.context.BaseContext,
        target: Callable[..., None],
        args_tail: Tuple[Any, ...],
        *,
        ack_timeout_s: float = 8.0,
    ) -> SubprocessRecordingHandle:
        """
        Khởi chạy `target(stop_ev, ack_q, *args_tail)`.
        ack_q nhận ("ok",) hoặc ("err", message) sau khi FFmpeg bắt đầu.
        """
        stop_ev = ctx.Event()
        ack_q: Queue = ctx.Queue(maxsize=1)
        proc = ctx.Process(
            target=target,
            args=(stop_ev, ack_q) + args_tail,
            daemon=False,
        )
        proc.start()
        try:
            msg = ack_q.get(timeout=ack_timeout_s)
        except Empty:
            stop_ev.set()
            proc.join(timeout=3.0)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=2.0)
            raise OSError(
                "Tiến trình ghi không phản hồi — kiểm tra ffmpeg và đường dẫn lưu file."
            ) from None
        if msg[0] == "err":
            stop_ev.set()
            proc.join(timeout=3.0)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=2.0)
            raise OSError(str(msg[1]))
        return SubprocessRecordingHandle(stop_ev, proc)

    def stop(self, timeout: float = 15.0) -> None:
        self._stop.set()
        self._proc.join(timeout=max(2.0, timeout))
        if self._proc.is_alive():
            self._proc.terminate()
            self._proc.join(timeout=2.0)
