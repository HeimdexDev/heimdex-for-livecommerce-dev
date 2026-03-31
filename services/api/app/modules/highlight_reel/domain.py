"""
Highlight reel scene selection algorithm.

Pure domain logic — NO imports from app.*, opensearchpy, sqlalchemy, or any I/O library.
All functions operate on plain dataclasses and return plain dataclasses.

Algorithm: "Max-Diversity Run Sampler"
  1. Filter out excluded videos
  2. Group scenes by video, detect consecutive runs
  3. Distribute time budget evenly across videos
  4. Score and select the best run per video
  5. Fill remaining budget with additional runs
  6. Order clips: most-appearances-first across videos, chronological within
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Domain types
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SceneRecord:
    scene_id: str
    video_id: str
    start_ms: int
    end_ms: int

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass(frozen=True)
class HighlightRequest:
    target_duration_ms: int
    excluded_video_ids: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class Run:
    video_id: str
    start_ms: int
    end_ms: int
    scene_count: int
    first_scene_id: str

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass
class SelectedClip:
    video_id: str
    scene_id: str
    start_ms: int
    end_ms: int
    timeline_start_ms: int = 0
    source_run_scene_count: int = 1

    @property
    def duration_ms(self) -> int:
        return self.end_ms - self.start_ms


@dataclass(frozen=True)
class HighlightPlan:
    clips: list[SelectedClip]
    total_duration_ms: int
    videos_used: int
    videos_available: int


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_CLIP_MS = 10_000       # Minimum clip duration (10s) — shorter feels too rushed
MIN_SCENE_MS = 1_000       # Ignore scenes shorter than 1s (noise)
MAX_TARGET_MS = 300_000    # 5 minutes
MIN_TARGET_MS = 30_000     # 30 seconds


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_highlight_plan(
    scenes: list[SceneRecord],
    request: HighlightRequest,
) -> HighlightPlan:
    """Top-level orchestrator: scenes + request → ordered clip plan."""
    target_ms = max(MIN_TARGET_MS, min(request.target_duration_ms, MAX_TARGET_MS))

    # 1. Filter
    eligible = _filter_excluded(scenes, request.excluded_video_ids)
    eligible = [s for s in eligible if s.duration_ms >= MIN_SCENE_MS]

    if not eligible:
        return HighlightPlan(clips=[], total_duration_ms=0, videos_used=0, videos_available=0)

    # 2. Group by video + detect runs
    grouped = _group_by_video(eligible)
    runs_by_video: dict[str, list[Run]] = {}
    for video_id, video_scenes in grouped.items():
        runs_by_video[video_id] = _detect_runs(video_scenes)

    # 3. Decide which videos to include and how much budget each gets
    video_ids_by_richness = sorted(
        runs_by_video.keys(),
        key=lambda vid: sum(r.duration_ms for r in runs_by_video[vid]),
        reverse=True,
    )
    selected_video_ids, per_video_budget = _distribute_budget(
        video_ids_by_richness, target_ms,
    )

    # 4. Select best clips
    clips = _select_clips(
        runs_by_video, selected_video_ids, per_video_budget, target_ms,
    )

    # 5. Order and assign timeline positions
    clips = _order_and_assign_timeline(clips, runs_by_video)

    total_ms = sum(c.duration_ms for c in clips)

    return HighlightPlan(
        clips=clips,
        total_duration_ms=total_ms,
        videos_used=len({c.video_id for c in clips}),
        videos_available=len(grouped),
    )


# ---------------------------------------------------------------------------
# Internal functions
# ---------------------------------------------------------------------------

def _filter_excluded(
    scenes: list[SceneRecord],
    excluded: frozenset[str],
) -> list[SceneRecord]:
    if not excluded:
        return scenes
    return [s for s in scenes if s.video_id not in excluded]


def _group_by_video(scenes: list[SceneRecord]) -> dict[str, list[SceneRecord]]:
    groups: dict[str, list[SceneRecord]] = {}
    for s in scenes:
        groups.setdefault(s.video_id, []).append(s)
    # Sort each group by start_ms (required for run detection)
    for vid in groups:
        groups[vid].sort(key=lambda s: s.start_ms)
    return groups


def _detect_runs(sorted_scenes: list[SceneRecord]) -> list[Run]:
    """Detect consecutive runs: scenes where scene[i].start_ms == scene[i-1].end_ms."""
    if not sorted_scenes:
        return []

    runs: list[Run] = []
    run_start = sorted_scenes[0]
    run_end = sorted_scenes[0]
    run_count = 1

    for i in range(1, len(sorted_scenes)):
        current = sorted_scenes[i]
        if current.start_ms == run_end.end_ms:
            # Consecutive — extend current run
            run_end = current
            run_count += 1
        else:
            # Gap — finalize previous run, start new one
            runs.append(Run(
                video_id=run_start.video_id,
                start_ms=run_start.start_ms,
                end_ms=run_end.end_ms,
                scene_count=run_count,
                first_scene_id=run_start.scene_id,
            ))
            run_start = current
            run_end = current
            run_count = 1

    # Finalize last run
    runs.append(Run(
        video_id=run_start.video_id,
        start_ms=run_start.start_ms,
        end_ms=run_end.end_ms,
        scene_count=run_count,
        first_scene_id=run_start.scene_id,
    ))

    return runs


def _distribute_budget(
    video_ids: list[str],
    target_ms: int,
    min_clip_ms: int = MIN_CLIP_MS,
) -> tuple[list[str], int]:
    """Decide how many videos to include and per-video budget.

    Returns (selected_video_ids, per_video_budget_ms).
    Maximizes video count while keeping each clip >= min_clip_ms.
    """
    if not video_ids:
        return [], 0

    max_videos = max(1, target_ms // min_clip_ms)
    selected = video_ids[:max_videos]
    per_video = target_ms // len(selected)

    return selected, per_video


def _score_run(
    run: Run,
    budget_ms: int,
    run_index: int,
    total_runs: int,
) -> float:
    """Score a run for selection. Higher = better.

    Factors:
      - duration_fit: how well the run's duration matches the budget
      - position: middle runs preferred over first/last (avoid intro/outro)
      - length_bonus: multi-scene runs feel more natural
    """
    # Duration fit: 1.0 when run.duration == budget, lower as it diverges
    if budget_ms > 0:
        ratio = min(run.duration_ms, budget_ms) / max(run.duration_ms, budget_ms)
        duration_fit = ratio  # 0.0-1.0
    else:
        duration_fit = 0.0

    # Position: middle of video scores higher
    if total_runs <= 1:
        position = 1.0
    elif total_runs == 2:
        position = 0.9
    else:
        # Normalize to 0.0-1.0 where 0.5 = middle
        normalized_pos = run_index / (total_runs - 1)  # 0.0 to 1.0
        # Bell curve centered at 0.5: peaks at middle, drops at edges
        position = 1.0 - 0.4 * abs(normalized_pos - 0.5) * 2  # 0.6 at edges, 1.0 at middle

    # Length bonus: multi-scene runs are more natural
    length_bonus = min(1.0, 0.6 + 0.1 * run.scene_count)  # 0.7 for 1 scene, caps at 1.0

    return duration_fit * 0.4 + position * 0.3 + length_bonus * 0.3


def _trim_run(run: Run, budget_ms: int) -> tuple[int, int]:
    """Trim a run to fit within budget. Takes from the middle of the run."""
    if run.duration_ms <= budget_ms:
        return run.start_ms, run.end_ms

    # Take from the middle
    excess = run.duration_ms - budget_ms
    trim_start = run.start_ms + excess // 2
    trim_end = trim_start + budget_ms

    return trim_start, trim_end


def _select_clips(
    runs_by_video: dict[str, list[Run]],
    selected_video_ids: list[str],
    per_video_budget: int,
    target_ms: int,
) -> list[SelectedClip]:
    """Select the best clips across videos to fill the target duration."""
    clips: list[SelectedClip] = []
    used_run_indices: dict[str, set[int]] = {vid: set() for vid in selected_video_ids}
    video_used_ms: dict[str, int] = {vid: 0 for vid in selected_video_ids}
    remaining_ms = target_ms

    # Pass 1: Pick the best run from each video
    for video_id in selected_video_ids:
        if remaining_ms <= 0:
            break

        runs = runs_by_video.get(video_id, [])
        if not runs:
            continue

        best_idx, best_score = -1, -1.0
        for i, run in enumerate(runs):
            score = _score_run(run, per_video_budget, i, len(runs))
            if score > best_score:
                best_score = score
                best_idx = i

        if best_idx < 0:
            continue

        run = runs[best_idx]
        clip_budget = min(per_video_budget, remaining_ms)
        start, end = _trim_run(run, clip_budget)
        clip_duration = end - start

        clips.append(SelectedClip(
            video_id=video_id,
            scene_id=run.first_scene_id,
            start_ms=start,
            end_ms=end,
            source_run_scene_count=run.scene_count,
        ))
        used_run_indices[video_id].add(best_idx)
        video_used_ms[video_id] += clip_duration
        remaining_ms -= clip_duration

    # Pass 2: Fill remaining budget with additional runs
    if remaining_ms > MIN_CLIP_MS:
        # Prefer videos with the most remaining runs
        for video_id in selected_video_ids:
            if remaining_ms <= MIN_CLIP_MS:
                break

            runs = runs_by_video.get(video_id, [])
            for i, run in enumerate(runs):
                if remaining_ms <= MIN_CLIP_MS:
                    break
                if i in used_run_indices[video_id]:
                    continue

                # Cap at 1.5x fair share per video
                if video_used_ms[video_id] >= per_video_budget * 1.5:
                    break

                start, end = _trim_run(run, remaining_ms)
                clip_duration = end - start

                clips.append(SelectedClip(
                    video_id=video_id,
                    scene_id=run.first_scene_id,
                    start_ms=start,
                    end_ms=end,
                    source_run_scene_count=run.scene_count,
                ))
                used_run_indices[video_id].add(i)
                video_used_ms[video_id] += clip_duration
                remaining_ms -= clip_duration

    return clips


def _order_and_assign_timeline(
    clips: list[SelectedClip],
    runs_by_video: dict[str, list[Run]],
) -> list[SelectedClip]:
    """Order clips and assign sequential timeline positions.

    Ordering strategy:
      - Videos ordered by total person-time (most appearances first)
      - Clips within a video in chronological order (start_ms)
    """
    if not clips:
        return []

    # Rank videos by total run duration (most content first)
    video_total_ms: dict[str, int] = {}
    for vid, runs in runs_by_video.items():
        video_total_ms[vid] = sum(r.duration_ms for r in runs)

    clips.sort(key=lambda c: (-video_total_ms.get(c.video_id, 0), c.start_ms))

    # Assign timeline positions
    cursor = 0
    for clip in clips:
        clip.timeline_start_ms = cursor
        cursor += clip.duration_ms

    return clips
