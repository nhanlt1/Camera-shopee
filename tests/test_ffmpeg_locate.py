"""resolve_ffmpeg: cấu hình và PATH."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from packrecorder.config import AppConfig
from packrecorder.ffmpeg_locate import pick_ffmpeg_in_resources_folder, resolve_ffmpeg


def test_resolve_from_config_path(tmp_path: Path) -> None:
    exe = tmp_path / "ffmpeg.exe"
    exe.write_bytes(b"")
    cfg = AppConfig(ffmpeg_path=str(exe))
    assert resolve_ffmpeg(cfg) == exe.resolve()


def test_resolve_requires_file_not_directory(tmp_path: Path) -> None:
    cfg = AppConfig(ffmpeg_path=str(tmp_path))
    with patch("packrecorder.ffmpeg_locate._dev_resources_ffmpeg", return_value=None):
        with patch("packrecorder.ffmpeg_locate.shutil.which", return_value=None):
            with patch("packrecorder.ffmpeg_locate._windows_extra_candidates", return_value=[]):
                with pytest.raises(FileNotFoundError):
                    resolve_ffmpeg(cfg)


def test_resolve_from_which(tmp_path: Path) -> None:
    cfg = AppConfig(ffmpeg_path="")
    fake = tmp_path / "ff.exe"
    with patch("packrecorder.ffmpeg_locate._dev_resources_ffmpeg", return_value=None):
        with patch("packrecorder.ffmpeg_locate.shutil.which", return_value=str(fake)):
            assert resolve_ffmpeg(cfg) == fake.resolve()


def test_pick_flat_ffmpeg_wins_over_nested(tmp_path: Path) -> None:
    rf = tmp_path / "ffmpeg"
    rf.mkdir()
    nested = rf / "ffmpeg-2099" / "bin"
    nested.mkdir(parents=True)
    (nested / "ffmpeg.exe").write_bytes(b"")
    flat = rf / "ffmpeg.exe"
    flat.write_bytes(b"")
    assert pick_ffmpeg_in_resources_folder(rf) == flat.resolve()


def test_pick_nested_newest_name(tmp_path: Path) -> None:
    rf = tmp_path / "ffmpeg"
    old = rf / "ffmpeg-2020" / "bin"
    old.mkdir(parents=True)
    (old / "ffmpeg.exe").write_bytes(b"a")
    new = rf / "ffmpeg-2026" / "bin"
    new.mkdir(parents=True)
    (new / "ffmpeg.exe").write_bytes(b"b")
    assert pick_ffmpeg_in_resources_folder(rf) == (new / "ffmpeg.exe").resolve()


def test_resolve_bundled_next_to_exe(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    app = tmp_path / "PackRecorder.exe"
    app.write_bytes(b"")
    ff = tmp_path / "ffmpeg.exe"
    ff.write_bytes(b"")
    fake_sys = SimpleNamespace(frozen=True, executable=str(app), _MEIPASS=None)
    monkeypatch.setattr("packrecorder.ffmpeg_locate.sys", fake_sys)
    cfg = AppConfig(ffmpeg_path="")
    with patch("packrecorder.ffmpeg_locate._dev_resources_ffmpeg", return_value=None):
        with patch("packrecorder.ffmpeg_locate.shutil.which", return_value=None):
            with patch("packrecorder.ffmpeg_locate._windows_extra_candidates", return_value=[]):
                assert resolve_ffmpeg(cfg) == ff.resolve()
