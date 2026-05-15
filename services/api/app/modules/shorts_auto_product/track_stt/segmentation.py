"""Live-block segmentation for the auto-shorts product pipeline.

Korean livecommerce VODs ship in a uniform three-act shape:
``intro (silent b-roll) → live host pitch → outro (silent b-roll)``.
The intro/outro blocks cycle stock footage with background music
but no host commentary; only the middle block has the host(s)
talking about products. Picking clip-candidates from the silent
blocks produces shorts that show a product slide but never get the
host's pitch — useless for short-form distribution.

This module is the deterministic gate that excludes those blocks
before any picker / scorer runs. Pure function, no I/O, no ML.

Contract is intentionally minimal — input is the OS scene dict
shape the rest of the auto-shorts pipeline already passes around
(see ``app.modules.search.scene_facets.SceneFacetsMixin.get_video_scenes``),
output is a tuple of opaque ``LiveBlock`` records the caller filters
on.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class LiveBlock:
    """A contiguous run of scenes where the host was actively talking.

    A "live" scene is one where STT produced any speech signal. Block
    boundaries fall between adjacent scenes whose live/silent status
    differs — so a 23-minute host pitch sandwiched by 14 minutes of
    silent intro and 47 minutes of silent outro produces exactly one
    ``LiveBlock`` spanning the middle 23 minutes.

    ``scene_ids`` is ordered by ``start_ms`` (same order the caller
    received from OpenSearch). Callers use it as the allowlist for
    clip-candidate selection.
    """

    start_ms: int
    end_ms: int
    scene_ids: tuple[str, ...]

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms

    @property
    def scene_count(self) -> int:
        return len(self.scene_ids)


@dataclass(frozen=True)
class PartitionSummary:
    """Counts for telemetry / eval. Cheap to compute alongside the
    blocks themselves so callers don't iterate twice."""

    total_scenes: int
    live_scenes: int
    excluded_scenes: int
    live_block_count: int
    total_ms: int
    live_total_ms: int
    longest_live_block_ms: int

    @property
    def exclusion_pct(self) -> float:
        if self.total_scenes == 0:
            return 0.0
        return 100.0 * self.excluded_scenes / self.total_scenes


def _is_live(scene: Mapping[str, Any]) -> bool:
    """A scene is live if ANY of the three STT signals fired.

    Defense in depth: some legacy OS docs only have one of these
    populated even though they all should agree. Picking the OR
    avoids false-silent classifications when one pipeline stage
    dropped its field.
    """
    speaker = scene.get("speaker_transcript")
    if isinstance(speaker, str) and speaker.strip():
        return True
    raw = scene.get("transcript_raw")
    if isinstance(raw, str) and raw.strip():
        return True
    seg_count = scene.get("speech_segment_count")
    if isinstance(seg_count, int) and seg_count > 0:
        return True
    return False


def partition_live_blocks(
    scenes: Sequence[Mapping[str, Any]],
    *,
    min_block_ms: int = 0,
) -> list[LiveBlock]:
    """Return contiguous live blocks, ordered by ``start_ms``.

    Args:
        scenes: OS scene dicts. MUST be ordered by ``start_ms``
            ascending (the existing ``get_video_scenes`` query sorts
            this way; callers that build their own list must respect
            this).
        min_block_ms: Drop live blocks whose duration is strictly
            shorter than this threshold. Default 0 (keep everything).
            Intended for filtering spurious 1-scene "speech" bursts
            (diarization picked up music) when a downstream caller
            wants to be conservative; the segmenter itself stays
            unopinionated and reports them by default so eval can see
            them.

    Returns:
        Empty list when the input has no live scenes (e.g., a video
        that was uploaded but never went live).
    """
    blocks: list[LiveBlock] = []
    run_start_ms: int | None = None
    run_end_ms: int = 0
    run_scene_ids: list[str] = []

    for scene in scenes:
        live = _is_live(scene)
        if live:
            scene_id = scene.get("scene_id")
            if not isinstance(scene_id, str):
                continue
            start = scene.get("start_ms", 0)
            end = scene.get("end_ms", 0)
            if not isinstance(start, int) or not isinstance(end, int):
                continue
            if run_start_ms is None:
                run_start_ms = start
            run_end_ms = max(run_end_ms, end)
            run_scene_ids.append(scene_id)
        else:
            if run_start_ms is not None:
                if run_end_ms - run_start_ms >= min_block_ms:
                    blocks.append(
                        LiveBlock(
                            start_ms=run_start_ms,
                            end_ms=run_end_ms,
                            scene_ids=tuple(run_scene_ids),
                        )
                    )
                run_start_ms = None
                run_end_ms = 0
                run_scene_ids = []

    if run_start_ms is not None and run_end_ms - run_start_ms >= min_block_ms:
        blocks.append(
            LiveBlock(
                start_ms=run_start_ms,
                end_ms=run_end_ms,
                scene_ids=tuple(run_scene_ids),
            )
        )

    return blocks


def summarize(
    scenes: Sequence[Mapping[str, Any]], blocks: Sequence[LiveBlock]
) -> PartitionSummary:
    """Compute the counts for telemetry / eval."""
    total_scenes = len(scenes)
    live_scenes = sum(b.scene_count for b in blocks)
    excluded_scenes = total_scenes - live_scenes

    video_start = scenes[0].get("start_ms", 0) if scenes else 0
    video_end = max((s.get("end_ms", 0) for s in scenes), default=0)
    if not isinstance(video_start, int):
        video_start = 0
    if not isinstance(video_end, int):
        video_end = 0
    total_ms = max(0, video_end - video_start)

    live_total_ms = sum(b.duration_ms for b in blocks)
    longest_live_block_ms = max((b.duration_ms for b in blocks), default=0)

    return PartitionSummary(
        total_scenes=total_scenes,
        live_scenes=live_scenes,
        excluded_scenes=excluded_scenes,
        live_block_count=len(blocks),
        total_ms=total_ms,
        live_total_ms=live_total_ms,
        longest_live_block_ms=longest_live_block_ms,
    )


def scene_ids_in_live_blocks(blocks: Sequence[LiveBlock]) -> frozenset[str]:
    """Flatten the per-block allowlists into a single membership set.

    Useful for the Phase 1 filter — converts a list of blocks into a
    cheap ``in`` test against a clip candidate's ``scene_id``.
    """
    out: set[str] = set()
    for b in blocks:
        out.update(b.scene_ids)
    return frozenset(out)
