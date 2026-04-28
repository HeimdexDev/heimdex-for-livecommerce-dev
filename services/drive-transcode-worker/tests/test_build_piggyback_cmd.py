"""Unit tests for `_build_nvenc_piggyback_cmd` — pure command-shape
assertions, no subprocess invocation.

These tests lock in the structural corrections that emerged from the
Phase 0.1 spike:
  * No `split=2` on CUDA surfaces — `[0:v]` referenced twice.
  * Detection branch terminated with `nullsink`, not `-map [D] -f null -`.
  * Proxy output comes first; `-movflags +faststart` binds to the proxy.
  * `-map 0:a?` with the `?` modifier so audio-less videos don't fail.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from src.tasks.transcode import _build_nvenc_piggyback_cmd


@pytest.fixture
def settings() -> SimpleNamespace:
    return SimpleNamespace(
        drive_proxy_max_height=720,
        drive_proxy_crf=23,
        drive_proxy_max_bitrate="2500k",
        drive_proxy_bufsize="5000k",
        drive_proxy_audio_bitrate="128k",
    )


def test_cmd_uses_cuda_hwaccel(settings) -> None:
    cmd = _build_nvenc_piggyback_cmd(
        Path("/in.mp4"), Path("/out.mp4"), Path("/scores.txt"), settings,
    )
    i = cmd.index("-hwaccel")
    assert cmd[i + 1] == "cuda"
    i = cmd.index("-hwaccel_output_format")
    assert cmd[i + 1] == "cuda"


def test_filter_complex_has_no_explicit_split_on_cuda(settings) -> None:
    cmd = _build_nvenc_piggyback_cmd(
        Path("/in.mp4"), Path("/out.mp4"), Path("/scores.txt"), settings,
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    # Spike finding: `split` is a software filter and breaks on CUDA
    # surfaces. We reference [0:v] twice instead.
    assert "split=2" not in fc
    assert fc.count("[0:v]") == 2


def test_filter_complex_uses_hwdownload_on_detection_branch(settings) -> None:
    cmd = _build_nvenc_piggyback_cmd(
        Path("/in.mp4"), Path("/out.mp4"), Path("/scores.txt"), settings,
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "hwdownload,format=nv12" in fc
    # Encode branch stays on GPU (scale_cuda, no hwdownload before it).
    assert "scale_cuda=-2:720" in fc


def test_detection_branch_terminates_with_nullsink(settings) -> None:
    cmd = _build_nvenc_piggyback_cmd(
        Path("/in.mp4"), Path("/out.mp4"), Path("/scores.txt"), settings,
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "metadata=print:file=/scores.txt,nullsink" in fc
    # Must NOT map the detection branch as a separate output — that was
    # the wrapped_avframe EINVAL bug on zero-cut videos.
    assert "[D]" not in fc
    # And there should be only one `-f null -` pair (if any) — ensure
    # our command does not carry a null-sink output file.
    assert "null" not in cmd or cmd.count("null") == 0


def test_proxy_output_comes_before_any_sink(settings) -> None:
    cmd = _build_nvenc_piggyback_cmd(
        Path("/in.mp4"), Path("/out.mp4"), Path("/scores.txt"), settings,
    )
    # The proxy output path must appear AFTER -movflags +faststart (so
    # those apply to the proxy) and there should be NO additional output
    # file after it.
    proxy_idx = cmd.index("/out.mp4")
    faststart_idx = cmd.index("+faststart")
    assert faststart_idx < proxy_idx
    # Nothing after the proxy output (no null sink, no second file).
    assert proxy_idx == len(cmd) - 1


def test_audio_mapping_is_optional(settings) -> None:
    cmd = _build_nvenc_piggyback_cmd(
        Path("/in.mp4"), Path("/out.mp4"), Path("/scores.txt"), settings,
    )
    # `-map 0:a?` — the `?` modifier makes the audio stream optional so
    # audio-less videos still encode successfully.
    maps = [cmd[i + 1] for i, v in enumerate(cmd) if v == "-map"]
    assert "0:a?" in maps


def test_encode_branch_uses_nvenc(settings) -> None:
    cmd = _build_nvenc_piggyback_cmd(
        Path("/in.mp4"), Path("/out.mp4"), Path("/scores.txt"), settings,
    )
    assert "h264_nvenc" in cmd
    assert "-preset" in cmd
    i = cmd.index("-preset")
    assert cmd[i + 1] == "p4"


def test_settings_propagated(settings) -> None:
    settings.drive_proxy_max_height = 1080
    settings.drive_proxy_crf = 20
    settings.drive_proxy_max_bitrate = "5000k"
    cmd = _build_nvenc_piggyback_cmd(
        Path("/in.mp4"), Path("/out.mp4"), Path("/scores.txt"), settings,
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "scale_cuda=-2:1080" in fc
    assert "20" in cmd
    assert "5000k" in cmd


def test_scores_file_path_embedded_exactly(settings) -> None:
    cmd = _build_nvenc_piggyback_cmd(
        Path("/in.mp4"),
        Path("/out.mp4"),
        Path("/var/tmp/scores.txt"),
        settings,
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "metadata=print:file=/var/tmp/scores.txt" in fc


def test_threshold_is_embedded_in_select_filter(settings) -> None:
    cmd = _build_nvenc_piggyback_cmd(
        Path("/in.mp4"), Path("/out.mp4"), Path("/s.txt"), settings,
        threshold=0.5,
    )
    fc = cmd[cmd.index("-filter_complex") + 1]
    assert "select='gt(scene,0.5)'" in fc
