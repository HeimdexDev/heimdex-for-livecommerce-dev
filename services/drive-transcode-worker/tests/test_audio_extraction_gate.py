"""Regression tests for the audio-extraction gate in
``_extract_audio_to_s3``.

Bug fixed 2026-04-29: ffmpeg `-vn -acodec pcm_s16le ...` exits 234
(EINVAL) when the input has no audio stream — common for dashcam,
silent, and screen-recorded footage. Pre-fix, the audio extraction
ran unconditionally with ``check=True`` inside
``_process_single_transcode``, so any audio-less video raised
``CalledProcessError`` out of the whole transcode step and discarded
the scenes/keyframes that had already been built.

This test pins the gate. The helper must:

* Return ``None`` (and skip ffmpeg entirely) when the probe reports no
  audio stream. Downstream gates STT publishing on a non-null key, so
  ``None`` is the supported "no STT for this video" signal.
* Run ffmpeg + upload exactly once when the probe reports audio.

Anti-pattern entry: see ``.claude/antipatterns.md`` —
"Unconditional ffmpeg audio extraction".
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest


def _stub(modname: str, **attrs: Any) -> ModuleType:
    """Install a sys.modules stub so ``transcode`` is importable in a
    bare local Python env (CI runs inside the container which has the
    real packages)."""
    m = ModuleType(modname)
    for k, v in attrs.items():
        setattr(m, k, v)
    sys.modules[modname] = m
    return m


# Top-level stubs run before `from src.tasks.transcode import ...`.
_stub("heimdex_worker_sdk", emit_event=lambda **k: None)
_stub("heimdex_worker_sdk.drive_keys", scene_manifest_s3_key=lambda *a, **k: "k")
_stub("heimdex_worker_sdk.s3", S3Client=MagicMock)
sys.modules.setdefault("boto3", MagicMock())
sys.modules.setdefault("requests", MagicMock())


def _probe(has_audio: bool, codec: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        has_audio=has_audio,
        audio_codec=codec if has_audio else None,
    )


def test_returns_none_when_proxy_has_no_audio_stream(tmp_path):
    """The dashcam case. Pre-fix this raised CalledProcessError."""
    from src.tasks.transcode import _extract_audio_to_s3

    s3 = MagicMock()
    audio_key_fn = MagicMock(side_effect=AssertionError(
        "must not derive an audio_s3_key when there is no audio"
    ))

    # Use the real subprocess to prove ffmpeg never runs — if the gate
    # were missing, this would attempt to invoke ffmpeg on a non-file.
    result = _extract_audio_to_s3(
        proxy_probe=_probe(has_audio=False),
        proxy_path=tmp_path / "proxy.mp4",   # does not exist
        temp_dir=tmp_path,
        s3=s3,
        audio_s3_key_fn=audio_key_fn,
        org_id_str="org-1",
        video_id="gd_dashcam",
        file_id="file-1",
    )

    assert result is None
    s3.upload_file.assert_not_called()
    audio_key_fn.assert_not_called()


def test_extracts_and_uploads_when_proxy_has_audio(tmp_path, monkeypatch):
    from src.tasks import transcode as t

    run_mock = MagicMock(return_value=MagicMock(returncode=0, stderr=b"", stdout=b""))
    monkeypatch.setattr(t.subprocess, "run", run_mock)

    s3 = MagicMock()
    audio_key_fn = MagicMock(return_value="org-1/audio/gd_live.wav")

    result = t._extract_audio_to_s3(
        proxy_probe=_probe(has_audio=True, codec="aac"),
        proxy_path=tmp_path / "proxy.mp4",
        temp_dir=tmp_path,
        s3=s3,
        audio_s3_key_fn=audio_key_fn,
        org_id_str="org-1",
        video_id="gd_live",
        file_id="file-1",
    )

    assert result == "org-1/audio/gd_live.wav"
    assert run_mock.call_count == 1, "ffmpeg must be invoked exactly once"

    cmd = run_mock.call_args.args[0]
    assert cmd[0] == "ffmpeg"
    assert "-vn" in cmd and "pcm_s16le" in cmd
    assert run_mock.call_args.kwargs.get("check") is True

    s3.upload_file.assert_called_once()
    upload_args = s3.upload_file.call_args
    assert upload_args.args[1] == "org-1/audio/gd_live.wav"
    assert upload_args.kwargs.get("content_type") == "audio/wav"


def test_propagates_ffmpeg_failure_when_audio_present(tmp_path, monkeypatch):
    """When the probe says audio IS present but ffmpeg still fails
    (corrupt stream, codec mismatch, disk full), the exception must
    propagate so the transcode is marked failed. The gate is for
    audio-less inputs — not a generic try/except."""
    from src.tasks import transcode as t
    import subprocess as _sp

    monkeypatch.setattr(t.subprocess, "run", MagicMock(
        side_effect=_sp.CalledProcessError(returncode=234, cmd=["ffmpeg"])
    ))

    with pytest.raises(_sp.CalledProcessError):
        t._extract_audio_to_s3(
            proxy_probe=_probe(has_audio=True, codec="aac"),
            proxy_path=tmp_path / "proxy.mp4",
            temp_dir=tmp_path,
            s3=MagicMock(),
            audio_s3_key_fn=lambda *a, **k: "k",
            org_id_str="org-1",
            video_id="gd_corrupt",
            file_id="file-1",
        )
