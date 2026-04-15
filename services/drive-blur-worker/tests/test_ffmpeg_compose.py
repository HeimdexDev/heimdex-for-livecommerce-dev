"""Unit tests for :mod:`src.tasks.ffmpeg_compose`.

The graph-construction tests are pure-string and run without ffmpeg.
``test_run_compose_end_to_end`` is gated on ffmpeg being installed so
the rest of the suite passes cleanly on laptops without it.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.tasks.ffmpeg_compose import (
    build_compose_command,
    build_filter_complex,
)


# ---------- build_filter_complex (pure string) ----------


def test_filter_complex_single_mask():
    g = build_filter_complex(1)
    assert "[0:v]format=yuva444p10le[src_a]" in g
    assert "[1:v]format=gray[m1]" in g
    # Single mask: no blend, rename m1 → mu via null.
    assert "[m1]null[mu]" in g
    assert "blend=all_mode=lighten" not in g
    assert "[src_a][mu]alphamerge[layer]" in g


def test_filter_complex_two_masks():
    g = build_filter_complex(2)
    assert "[1:v]format=gray[m1]" in g
    assert "[2:v]format=gray[m2]" in g
    # One blend, producing mu directly.
    assert "[m1][m2]blend=all_mode=lighten[mu]" in g
    assert "[src_a][mu]alphamerge[layer]" in g
    # No intermediate uN labels for exactly two masks.
    assert "[u2]" not in g


def test_filter_complex_three_masks():
    g = build_filter_complex(3)
    assert "[m1][m2]blend=all_mode=lighten[u2]" in g
    assert "[u2][m3]blend=all_mode=lighten[mu]" in g
    assert "[src_a][mu]alphamerge[layer]" in g


def test_filter_complex_five_masks_chain_shape():
    g = build_filter_complex(5)
    # The chain should be strictly linear: m1+m2→u2, u2+m3→u3,
    # u3+m4→u4, u4+m5→mu. Verify both the intermediate labels and the
    # final mu label.
    assert "[m1][m2]blend=all_mode=lighten[u2]" in g
    assert "[u2][m3]blend=all_mode=lighten[u3]" in g
    assert "[u3][m4]blend=all_mode=lighten[u4]" in g
    assert "[u4][m5]blend=all_mode=lighten[mu]" in g
    # And no stray final-label collisions.
    assert g.count("[mu]") == 2  # one from the blend out, one from the alphamerge in


def test_filter_complex_zero_masks_rejected():
    with pytest.raises(ValueError):
        build_filter_complex(0)


# ---------- build_compose_command (argv) ----------


def test_compose_command_has_prores_flags(tmp_path: Path):
    src = tmp_path / "src.mp4"
    mask = tmp_path / "face.mkv"
    out = tmp_path / "layer.mov"
    argv = build_compose_command(
        source_path=src,
        mask_paths=[mask],
        output_path=out,
        ffmpeg_binary="/usr/bin/ffmpeg",
    )
    # Input ordering: source first, then masks.
    assert argv[argv.index("-i") + 1] == str(src)
    # Every mask input is present.
    assert str(mask) in argv
    # Output codec flags for NLE-grade 4444 + alpha.
    assert "prores_ks" in argv
    i_profile = argv.index("-profile:v")
    assert argv[i_profile + 1] == "4"
    i_pix = argv.index("-pix_fmt")
    assert argv[i_pix + 1] == "yuva444p10le"
    # Apple vendor tag so QuickTime + FCP recognize the alpha channel.
    i_vendor = argv.index("-vendor")
    assert argv[i_vendor + 1] == "apl0"
    # Strip audio — layer is video-only.
    assert "-an" in argv
    # Output path is the last positional argument.
    assert argv[-1] == str(out)


def test_compose_command_multiple_masks_input_order(tmp_path: Path):
    src = tmp_path / "src.mp4"
    masks = [tmp_path / "face.mkv", tmp_path / "license_plate.mkv", tmp_path / "logo.mkv"]
    argv = build_compose_command(
        source_path=src,
        mask_paths=masks,
        output_path=tmp_path / "layer.mov",
        ffmpeg_binary="ffmpeg",
    )
    # Every mask path appears after its own -i flag.
    i_flags = [idx for idx, tok in enumerate(argv) if tok == "-i"]
    # 1 source + 3 masks = 4 input flags.
    assert len(i_flags) == 4
    inputs = [argv[idx + 1] for idx in i_flags]
    assert inputs[0] == str(src)
    assert inputs[1:] == [str(m) for m in masks]


def test_compose_command_empty_masks_rejected(tmp_path: Path):
    with pytest.raises(ValueError):
        build_compose_command(
            source_path=tmp_path / "src.mp4",
            mask_paths=[],
            output_path=tmp_path / "out.mov",
            ffmpeg_binary="ffmpeg",
        )


# ---------- end-to-end (requires ffmpeg on PATH) ----------


requires_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None,
    reason="ffmpeg not installed",
)


@requires_ffmpeg
def test_run_compose_end_to_end(tmp_path: Path):
    """Compose a 5-frame synthetic source + one synthetic mask into a
    real ProRes 4444 ``.mov`` and verify the output exists and is
    non-empty. Does not inspect the alpha channel bit-for-bit — that
    belongs in a slower visual regression test.
    """
    import subprocess

    ffmpeg = shutil.which("ffmpeg")
    assert ffmpeg is not None

    src = tmp_path / "src.mp4"
    mask = tmp_path / "face.mkv"
    out = tmp_path / "layer.mov"

    # 5-frame 64x48 test source via lavfi ``color`` + lossless H.264.
    subprocess.run(  # noqa: S603 — fixed args
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=red:s=64x48:r=10:d=0.5",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(src),
        ],
        check=True,
    )
    # Matching 5-frame 64x48 mask: full white → every pixel blurred.
    subprocess.run(  # noqa: S603
        [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", "color=c=white:s=64x48:r=10:d=0.5",
            "-c:v", "ffv1", "-pix_fmt", "gray", "-g", "1",
            str(mask),
        ],
        check=True,
    )

    from src.tasks.ffmpeg_compose import run_compose

    result_path = run_compose(
        source_path=src,
        mask_paths=[mask],
        output_path=out,
    )
    assert result_path == out
    assert out.exists()
    assert out.stat().st_size > 0

    # Probe the output to confirm it advertises yuva (alpha-bearing).
    probe = subprocess.run(  # noqa: S603
        [
            ffmpeg, "-hide_banner", "-i", str(out),
        ],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    stderr = probe.stderr.decode("utf-8", errors="replace")
    assert "yuva" in stderr.lower()
