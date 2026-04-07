from pathlib import Path
from unittest.mock import MagicMock, patch

from packrecorder.ffmpeg_pipe_recorder import FFmpegPipeRecorder


@patch("packrecorder.ffmpeg_pipe_recorder.assign_process_to_job_object")
@patch("packrecorder.ffmpeg_pipe_recorder.subprocess.Popen")
def test_start_builds_command_and_writes_header(mock_popen, _mock_job, tmp_path: Path):
    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.poll.return_value = None
    proc.pid = 4242
    mock_popen.return_value = proc
    out = tmp_path / "o.mp4"
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_text("fake", encoding="utf-8")
    rec = FFmpegPipeRecorder(ffmpeg_exe=ffmpeg, width=320, height=240, fps=15)
    rec.start(out)
    args, _kwargs = mock_popen.call_args
    cmd = args[0]
    assert "-f" in cmd and "rawvideo" in cmd
    assert str(out) in cmd
    assert "+faststart" in cmd
    assert "yuv420p" in cmd
    assert "main" in cmd
    assert "zerolatency" in cmd
    rec.stop()
    proc.stdin.close.assert_called()
    proc.wait.assert_called()


@patch("packrecorder.ffmpeg_pipe_recorder.assign_process_to_job_object")
@patch("packrecorder.ffmpeg_pipe_recorder.subprocess.Popen")
def test_start_odd_dimensions_adds_scale_filter(mock_popen, _mock_job, tmp_path: Path):
    proc = MagicMock()
    proc.stdin = MagicMock()
    proc.poll.return_value = None
    proc.pid = 4242
    mock_popen.return_value = proc
    out = tmp_path / "o.mp4"
    ffmpeg = tmp_path / "ffmpeg.exe"
    ffmpeg.write_text("fake", encoding="utf-8")
    rec = FFmpegPipeRecorder(ffmpeg_exe=ffmpeg, width=641, height=480, fps=15)
    rec.start(out)
    args, _kwargs = mock_popen.call_args
    cmd = args[0]
    assert "-vf" in cmd
    idx = cmd.index("-vf")
    assert "trunc(iw/2)*2" in cmd[idx + 1]
    rec.stop()
