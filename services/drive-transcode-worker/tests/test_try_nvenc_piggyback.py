"""Tests for the `_try_nvenc_piggyback` helper — subprocess and parser
interactions, failure-mode fallback semantics.

Scope: verify that every plausible failure path returns ``None`` so
the caller falls through to the legacy NVENC + libx264 chain, and that
the success path returns parsed cuts. Does NOT exercise the full
_process_single_transcode flow — that's pre-existing code unchanged
for the flag=false case.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# Make sure the dynamic `heimdex_media_pipelines.scenes.ffmpeg_metadata`
# module is importable when the test runs without the pipelines package
# installed.
@pytest.fixture(autouse=True)
def _stub_pipelines_metadata_module(monkeypatch):
    """Install a stub module so `_try_nvenc_piggyback`'s lazy import
    resolves without requiring the real pipelines lib on the test path.
    """
    stub = SimpleNamespace()
    stub.parse_ffmpeg_metadata_file = MagicMock(return_value=[])
    monkeypatch.setitem(
        sys.modules,
        "heimdex_media_pipelines.scenes.ffmpeg_metadata",
        stub,
    )
    yield stub


@pytest.fixture
def settings() -> SimpleNamespace:
    return SimpleNamespace(
        drive_proxy_max_height=720,
        drive_proxy_crf=23,
        drive_proxy_max_bitrate="2500k",
        drive_proxy_bufsize="5000k",
        drive_proxy_audio_bitrate="128k",
    )


def _fake_run_result(rc: int, stderr: bytes = b"") -> MagicMock:
    m = MagicMock()
    m.returncode = rc
    m.stderr = stderr
    return m


def test_success_returns_parsed_cuts(settings, tmp_path, _stub_pipelines_metadata_module):
    from src.tasks.transcode import _try_nvenc_piggyback

    scores = tmp_path / "scores.txt"
    # `_try_nvenc_piggyback` unlinks the scores file before running
    # subprocess.run. Mimic real ffmpeg behavior by having the mocked
    # subprocess.run write the file as its side effect.
    def _run_and_write(*args, **kwargs):
        scores.write_text("frame:0 pts:1 pts_time:1.0\nlavfi.scene_score=0.5\n")
        return _fake_run_result(0)

    _stub_pipelines_metadata_module.parse_ffmpeg_metadata_file = MagicMock(
        return_value=[1000, 3000]
    )

    with patch("src.tasks.transcode.subprocess.run", side_effect=_run_and_write):
        result = _try_nvenc_piggyback(
            input_path=tmp_path / "in.mp4",
            output_path=tmp_path / "out.mp4",
            scores_file=scores,
            settings=settings,
            video_id="vid-1",
        )
    assert result == [1000, 3000]


def test_ffmpeg_nonzero_exit_returns_none(settings, tmp_path):
    from src.tasks.transcode import _try_nvenc_piggyback

    with patch("src.tasks.transcode.subprocess.run",
               return_value=_fake_run_result(1, b"oops")):
        result = _try_nvenc_piggyback(
            input_path=tmp_path / "in.mp4",
            output_path=tmp_path / "out.mp4",
            scores_file=tmp_path / "scores.txt",
            settings=settings,
            video_id="vid-1",
        )
    assert result is None


def test_scores_file_missing_returns_none(settings, tmp_path):
    from src.tasks.transcode import _try_nvenc_piggyback

    # Subprocess succeeds but the scores file doesn't exist — means the
    # filter chain silently skipped the detection branch (e.g. filter
    # graph parsed but no frames reached nullsink).
    with patch("src.tasks.transcode.subprocess.run",
               return_value=_fake_run_result(0)):
        result = _try_nvenc_piggyback(
            input_path=tmp_path / "in.mp4",
            output_path=tmp_path / "out.mp4",
            scores_file=tmp_path / "does_not_exist.txt",
            settings=settings,
            video_id="vid-1",
        )
    assert result is None


def test_parser_error_returns_none(settings, tmp_path, _stub_pipelines_metadata_module):
    from src.tasks.transcode import _try_nvenc_piggyback

    scores = tmp_path / "scores.txt"
    scores.write_text("garbage")
    _stub_pipelines_metadata_module.parse_ffmpeg_metadata_file = MagicMock(
        side_effect=RuntimeError("format drift"),
    )

    with patch("src.tasks.transcode.subprocess.run",
               return_value=_fake_run_result(0)):
        result = _try_nvenc_piggyback(
            input_path=tmp_path / "in.mp4",
            output_path=tmp_path / "out.mp4",
            scores_file=scores,
            settings=settings,
            video_id="vid-1",
        )
    assert result is None


def test_pre_run_unlinks_existing_scores_file(settings, tmp_path, _stub_pipelines_metadata_module):
    """metadata=print APPENDS to an existing file. On SQS redelivery the
    temp_dir may survive an earlier partial run. The helper must unlink
    the scores file before invoking ffmpeg.
    """
    from src.tasks.transcode import _try_nvenc_piggyback

    scores = tmp_path / "scores.txt"
    scores.write_text("STALE-CONTENT-FROM-PREVIOUS-RUN\n")
    assert scores.is_file()

    # Pretend the new ffmpeg run doesn't write to the file (rc=0 but
    # no output) — we want to prove the unlink happened regardless of
    # whether ffmpeg replaces the file.
    def _run_stub(*args, **kwargs):
        assert not scores.is_file(), (
            "scores file must be deleted before ffmpeg invocation; "
            "otherwise retries will concatenate timestamps"
        )
        scores.write_text("frame:0 pts:1 pts_time:1.0\nlavfi.scene_score=0.5\n")
        return _fake_run_result(0)

    _stub_pipelines_metadata_module.parse_ffmpeg_metadata_file = MagicMock(
        return_value=[1000]
    )
    with patch("src.tasks.transcode.subprocess.run", side_effect=_run_stub):
        result = _try_nvenc_piggyback(
            input_path=tmp_path / "in.mp4",
            output_path=tmp_path / "out.mp4",
            scores_file=scores,
            settings=settings,
            video_id="vid-1",
        )
    assert result == [1000]
