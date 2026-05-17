"""FFmpeg subprocess helpers for the blur layer export task.

Builds the ``filter_complex`` graph that composites a source proxy +
N per-category grayscale masks into a single ProRes 4444 ``.mov`` with
alpha set on the union of the masked regions. Customers drop the
``.mov`` on top of the original in Premiere / DaVinci / FCP and apply
whatever blur strength they want in their NLE.

The graph is built dynamically because the category subset the
customer selects at export time is variable (1–5 masks). Kept in its
own module so the filter-string construction is easy to unit-test
without booting ffmpeg itself.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)


def resolve_ffmpeg_binary() -> str:
    binary = shutil.which("ffmpeg")
    if not binary:
        raise RuntimeError(
            "ffmpeg binary not found on PATH; drive-blur-worker requires "
            "ffmpeg for layer export composition"
        )
    return binary


def build_filter_complex(num_masks: int) -> str:
    """Compose the ``-filter_complex`` string for N mask inputs.

    Layout:
      * input ``[0:v]`` is the source proxy (RGB)
      * inputs ``[1:v]`` .. ``[N:v]`` are the per-category grayscale
        FFV1 masks

    Output label is always ``[layer]`` regardless of N.

    For N=1 we skip the union blend step and wire the single mask
    directly into ``alphamerge``. For N>=2 we chain N-1 ``lighten``
    blends to compute the pixel-wise max across all masks (the union
    of blurred regions), then set it as the alpha of the source.

    Raises ``ValueError`` if ``num_masks < 1`` — an export with zero
    masks is always a programming error.
    """
    if num_masks < 1:
        raise ValueError(f"num_masks must be >= 1, got {num_masks}")

    parts: list[str] = []

    # Normalize the source to yuva444p10le so it has an alpha channel
    # slot for alphamerge to populate.
    parts.append("[0:v]format=yuva444p10le[src_a]")

    # Normalize every mask input to gray so alphamerge can use its
    # luma as the alpha plane.
    for i in range(1, num_masks + 1):
        parts.append(f"[{i}:v]format=gray[m{i}]")

    # Build the mask union via chained lighten blends. For N=1 this
    # loop is skipped and we rename m1 → mu via a null filter so the
    # downstream alphamerge can reference a single stable label.
    if num_masks == 1:
        parts.append("[m1]null[mu]")
    else:
        prev = "m1"
        for i in range(2, num_masks + 1):
            label = "mu" if i == num_masks else f"u{i}"
            parts.append(f"[{prev}][m{i}]blend=all_mode=lighten[{label}]")
            prev = label

    # Merge the union mask into the alpha channel of the source.
    parts.append("[src_a][mu]alphamerge[layer]")

    return ";".join(parts)


def build_compose_command(
    *,
    source_path: Path,
    mask_paths: Sequence[Path],
    output_path: Path,
    ffmpeg_binary: str | None = None,
) -> list[str]:
    """Return the argv for the full FFmpeg compose invocation.

    ProRes 4444 profile (profile:v 4) + ``yuva444p10le`` gives NLE
    editors a matte-ready clip with lossless alpha. The ``apl0`` vendor
    tag is what Apple-ecosystem tools (FCP, QuickTime) look for before
    treating the alpha channel as usable. Audio is stripped — the
    layer is video-only by design.
    """
    if not mask_paths:
        raise ValueError("mask_paths must be non-empty")
    binary = ffmpeg_binary or resolve_ffmpeg_binary()

    argv: list[str] = [
        binary,
        "-y",
        "-hide_banner",
        "-loglevel", "error",
    ]
    argv += ["-i", str(source_path)]
    for path in mask_paths:
        argv += ["-i", str(path)]

    argv += [
        "-filter_complex",
        build_filter_complex(len(mask_paths)),
    ]
    argv += [
        "-map", "[layer]",
        "-c:v", "prores_ks",
        "-profile:v", "4",             # ProRes 4444 (matte-compatible)
        "-pix_fmt", "yuva444p10le",    # 10-bit 4:4:4 + alpha
        "-vendor", "apl0",             # Apple vendor tag for NLE compat
        "-an",                          # strip audio
        str(output_path),
    ]
    return argv


def run_compose(
    *,
    source_path: Path,
    mask_paths: Sequence[Path],
    output_path: Path,
    timeout: float = 1800.0,
) -> Path:
    """Run the compose command and return the output path on success.

    Raises ``RuntimeError`` with ffmpeg's stderr attached on any
    non-zero exit code. Timeout defaults to 30 min, matching the
    worker's default lease.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    argv = build_compose_command(
        source_path=source_path,
        mask_paths=mask_paths,
        output_path=output_path,
    )
    logger.info(
        "ffmpeg_compose_start",
        extra={
            "source": str(source_path),
            "mask_count": len(mask_paths),
            "output": str(output_path),
        },
    )
    result = subprocess.run(  # noqa: S603 — argv built from validated paths
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"ffmpeg compose failed (rc={result.returncode}): {stderr[:2000]}"
        )
    if not output_path.exists() or output_path.stat().st_size == 0:
        raise RuntimeError(
            f"ffmpeg compose produced no output at {output_path}"
        )
    return output_path


__all__ = [
    "build_compose_command",
    "build_filter_complex",
    "resolve_ffmpeg_binary",
    "run_compose",
]
