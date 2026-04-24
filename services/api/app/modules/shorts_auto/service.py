"""Auto-shorts orchestration: fetch → score → concat → (optional) render.

This service is intentionally thin. It owns *no* business logic about
scoring (lives in contracts), no logic about clip assembly (lives in
contracts), and no logic about rendering (lives in shorts_render).

Loose-coupling enforcement:
  - Reaches into ``shorts_render`` only via the public
    ``ShortsRenderService.create_render_job(...)`` interface.
  - Reads scenes only through the injected scene OS client (via
    ``AutoShortsSelector``).
  - Validates video existence + duration via the
    ``DriveFileRepository.get_by_video_id`` public interface.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, status

from app.config import get_settings
from app.logging_config import get_logger
from app.modules.drive.repository import DriveFileRepository
from app.modules.shorts_auto.schemas import (
    AutoClipResponse,
    AutoRenderRequest,
    AutoSelectRequest,
    AutoSelectResponse,
    ClipMemberResponse,
    ScoringModeRequest,
)
from app.modules.shorts_auto.scorers import (
    PureSceneScorer,
    SceneScorer,
    ScorerBudgetExceededError,
    ScorerFallbackSignal,
    ScoringContext,
)
from app.modules.shorts_auto.selector import AutoShortsSelector
from app.modules.shorts_render.schemas import RenderJobCreate, RenderJobResponse
from app.modules.shorts_render.service import ShortsRenderService

from heimdex_media_contracts.composition import (
    CompositionSpec,
    OutputSpec,
    SceneClipSpec,
)
from heimdex_media_contracts.shorts.concatenator import (
    AutoClip,
    ClipMember,
    build_clips,
)
from heimdex_media_contracts.shorts.scorer import ScoringMode

logger = get_logger(__name__)


def _to_contract_mode(req_mode: ScoringModeRequest) -> ScoringMode:
    """Bridge request enum → contracts enum. Values match by design."""
    return ScoringMode(req_mode.value)


def _auto_clip_to_response(clip: AutoClip) -> AutoClipResponse:
    return AutoClipResponse(
        scene_ids=clip.scene_ids,
        members=[
            ClipMemberResponse(
                scene_id=m.scene_id,
                start_ms=m.start_ms,
                end_ms=m.end_ms,
                score=m.score,
            )
            for m in clip.members
        ],
        start_ms=clip.start_ms,
        end_ms=clip.end_ms,
        duration_ms=clip.duration_ms,
        score=clip.score,
        reasons=clip.reasons,
        is_continuous=clip.is_continuous,
    )


def _build_llm_single_clip(
    scored: list[Any],
    *,
    target_duration_sec: int,
) -> list[AutoClip]:
    """Build one AutoClip from all LLM-picked (eligible) scenes.

    Bypasses ``build_clips`` because the LLM curates — it hand-picks
    the scenes that should form the short, so packing them into
    independently-validated sub-clips fights the curation. Instead we
    take every eligible scene, sort chronologically, and make one clip
    whose members are the picks. If the LLM picked so many scenes that
    the total runs over ``target_duration_sec * 2``, the trailing picks
    are dropped to stay near target — same spirit as the 5-min
    composition cap that lives in ``_compose``.
    """
    picks = sorted(
        (s for s in scored if s.breakdown.eligible),
        key=lambda s: s.scene.start_ms,
    )
    if not picks:
        return []

    hard_cap_ms = target_duration_sec * 1000 * 2  # 2× target ≈ runaway guard
    members: list[ClipMember] = []
    total_ms = 0
    for s in picks:
        dur = s.scene.end_ms - s.scene.start_ms
        if dur <= 0:
            continue
        if total_ms + dur > hard_cap_ms and members:
            break
        members.append(
            ClipMember(
                scene_id=s.scene.scene_id,
                start_ms=s.scene.start_ms,
                end_ms=s.scene.end_ms,
                score=float(s.breakdown.total),
            )
        )
        total_ms += dur

    if not members:
        return []

    scores = [m.score for m in members]
    avg_score = sum(scores) / len(scores) if scores else 0.0
    scene_ids = [m.scene_id for m in members]
    # ``is_continuous`` reflects whether picks are adjacent scene indices
    # — LLM picks are often NOT contiguous so default to False.
    indices = sorted(s.scene.index for s in picks[: len(members)])
    is_continuous = all(indices[i + 1] - indices[i] == 1 for i in range(len(indices) - 1))
    return [
        AutoClip(
            scene_ids=scene_ids,
            members=members,
            start_ms=members[0].start_ms,
            end_ms=members[-1].end_ms,
            duration_ms=total_ms,
            score=avg_score,
            reasons=[r for s in picks[: len(members)] for r in s.breakdown.reasons][:5],
            is_continuous=is_continuous,
        )
    ]


def _empty_response(req: AutoSelectRequest, reason: str) -> AutoSelectResponse:
    return AutoSelectResponse(
        video_id=req.video_id,
        mode=req.mode,
        clips=[],
        total_duration_ms=0,
        skipped_reason=reason,
    )


class ShortsAutoService:
    def __init__(
        self,
        selector: AutoShortsSelector,
        drive_file_repo: DriveFileRepository,
        shorts_render_service: ShortsRenderService,
        scorer: SceneScorer,
    ) -> None:
        self.selector = selector
        self.drive_file_repo = drive_file_repo
        self.shorts_render_service = shorts_render_service
        self.scorer = scorer

    async def auto_select(
        self,
        org_id: UUID,
        user_id: UUID,
        req: AutoSelectRequest,
    ) -> AutoSelectResponse:
        """Score scenes and assemble candidate clips. No side effects."""
        settings = get_settings()
        contract_mode = _to_contract_mode(req.mode)

        # Validate video exists in the org and meets minimum duration.
        drive_file = await self.drive_file_repo.get_by_video_id(org_id, req.video_id)
        if drive_file is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"video {req.video_id!r} not found in org",
            )

        proxy_duration_ms = drive_file.proxy_duration_ms or 0
        min_video_ms = settings.auto_shorts_min_video_duration_sec * 1000
        if proxy_duration_ms and proxy_duration_ms < min_video_ms:
            return _empty_response(req, "video_too_short")
        if not proxy_duration_ms:
            # Transcode hasn't populated duration yet. We proceed — the
            # scene corpus check below will return empty if there's
            # nothing to select from — but surface the condition in logs
            # so operators can distinguish "no scenes yet" from
            # "scenes exist but none qualify".
            logger.warning(
                "auto_shorts_unknown_video_duration",
                org_id=str(org_id),
                user_id=str(user_id),
                video_id=req.video_id,
            )

        # Fetch candidates with mode-aware OS pre-filter.
        scenes = await self.selector.fetch_candidates(
            org_id=org_id,
            video_id=req.video_id,
            mode=contract_mode,
            person_cluster_id=req.person_cluster_id,
        )
        if not scenes:
            return _empty_response(req, "no_candidate_scenes_after_filter")

        # Score via injected scorer (pure or LLM). On LLM failure we
        # transparently retry with the pure scorer so the endpoint never
        # 5xxs on an LLM defect. The ``scorer_used`` string flows into
        # the response so the UI can show "AI selected" vs fallback.
        scoring_context = ScoringContext(
            mode=contract_mode,
            person_cluster_id=req.person_cluster_id,
            target_duration_sec=req.target_duration_sec,
            video_id=req.video_id,
            video_title=getattr(drive_file, "file_name", None),
        )
        scorer_used = self.scorer.name
        try:
            scored = await self.scorer.score(scenes, scoring_context)
        except (ScorerFallbackSignal, ScorerBudgetExceededError) as e:
            logger.warning(
                "auto_shorts_scorer_fallback",
                org_id=str(org_id),
                user_id=str(user_id),
                video_id=req.video_id,
                primary_scorer=self.scorer.name,
                reason=type(e).__name__,
                detail=str(e)[:200],
            )
            fallback = PureSceneScorer()
            scored = await fallback.score(scenes, scoring_context)
            scorer_used = fallback.name

        eligible_count = sum(1 for s in scored if s.breakdown.eligible)
        if eligible_count == 0:
            return _empty_response(req, "no_scenes_passed_eligibility")

        # Concatenate. The LLM scorer curates — it picks a small set of
        # scenes intended as the entire short, with non-picks marked
        # eligible=False. ``build_clips`` treats each eligible scene as
        # a candidate and tries to pack ``count`` × ``target_duration``
        # worth of clips from them; with a curated handful of picks it
        # nearly always returns 0 clips against the default min_duration
        # floor. So on the LLM path we build ONE chronological clip
        # from the picks directly — matches the user mental model of a
        # single ~60s short. Pure scorer keeps ``build_clips`` intact.
        if scorer_used == "llm":
            clips = _build_llm_single_clip(scored, target_duration_sec=req.target_duration_sec)
        else:
            clips = build_clips(
                scored,
                count=req.count,
                target_duration_ms=req.target_duration_sec * 1000,
                min_duration_ms=req.min_duration_sec * 1000,
                prefer_continuous=req.prefer_continuous,
            )

        if not clips:
            return _empty_response(req, "no_clips_met_min_duration")

        clip_responses = [_auto_clip_to_response(c) for c in clips]
        total_duration_ms = sum(c.duration_ms for c in clips)

        logger.info(
            "auto_shorts_select_returned",
            org_id=str(org_id),
            user_id=str(user_id),
            video_id=req.video_id,
            mode=req.mode.value,
            person_cluster_id=req.person_cluster_id,
            scorer=scorer_used,
            primary_scorer=self.scorer.name,
            candidates=len(scenes),
            eligible=eligible_count,
            clips_returned=len(clips),
            total_duration_ms=total_duration_ms,
            lowest_score=min((c.score for c in clips), default=0.0),
        )

        return AutoSelectResponse(
            video_id=req.video_id,
            mode=req.mode,
            clips=clip_responses,
            total_duration_ms=total_duration_ms,
            skipped_reason=None,
            scorer=scorer_used,  # type: ignore[arg-type]
        )

    async def auto_render(
        self,
        org_id: UUID,
        user_id: UUID,
        req: AutoRenderRequest,
    ) -> RenderJobResponse:
        """Run auto-select then delegate to the existing render pipeline."""
        if req.auto_caption:
            # Auto-caption is P4. Reject explicitly so callers get a
            # clean signal instead of silently dropping the flag.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="auto_caption is not yet enabled (deferred to phase 4)",
            )

        select_req = AutoSelectRequest(
            video_id=req.video_id,
            mode=req.mode,
            person_cluster_id=req.person_cluster_id,
            count=req.count,
            target_duration_sec=req.target_duration_sec,
            min_duration_sec=req.min_duration_sec,
            prefer_continuous=req.prefer_continuous,
        )
        selection = await self.auto_select(org_id, user_id, select_req)
        # ``count`` is a hint, not a hard floor. The user-visible goal is
        # a single rendered short; CompositionSpec packs whatever clips
        # we have onto the timeline regardless of how many. We only 422
        # when there's genuinely nothing to render. A stricter ratio
        # check (e.g. < 50% of requested) is a candidate for later if
        # render quality suffers from sparse selections.
        if not selection.clips:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail=(
                    "no qualifying clips "
                    f"({selection.skipped_reason or 'low corpus'}) "
                    f"[scorer={selection.scorer}]"
                ),
            )

        composition = self._compose(req, selection.clips)
        title = req.title or f"Auto {req.mode.value} ({len(selection.clips)} clips)"
        payload = RenderJobCreate(
            video_id=req.video_id,
            title=title,
            composition=composition,
        )

        logger.info(
            "auto_shorts_render_delegated",
            org_id=str(org_id),
            user_id=str(user_id),
            video_id=req.video_id,
            mode=req.mode.value,
            clip_count=len(selection.clips),
        )
        return await self.shorts_render_service.create_render_job(
            org_id=org_id,
            user_id=user_id,
            payload=payload,
        )

    def _compose(
        self,
        req: AutoRenderRequest,
        clips: list[AutoClipResponse],
    ) -> CompositionSpec:
        """Build a CompositionSpec from selected clips.

        Emits one ``SceneClipSpec`` per ``ClipMemberResponse`` so each
        SceneClipSpec's source span stays inside its named scene's bounds
        — required by ``ShortsRenderService._validate_scene_clips``.

        Clips are packed back-to-back on the composition timeline in the
        order they appear (chronological, set by the concatenator).
        Within a clip, members are already chronologically sorted.

        ``CompositionSpec._validate_max_duration`` enforces a 5-min hard
        cap (300_000 ms). ``count=5`` × ``target_duration_sec=60`` can hit
        exactly 300s; overshoot headroom in the concatenator can push
        individual clips above 60s. If the cumulative timeline would
        exceed the cap, we truncate the trailing member's ``end_ms`` to
        fit — done here so the concatenator stays mode-agnostic and the
        trimming logic is next to the constraint it enforces.
        """
        scene_clips: list[SceneClipSpec] = []
        timeline_cursor_ms = 0
        max_total_ms = 5 * 60 * 1000  # mirrors composition.schemas cap

        truncated = False
        for clip in clips:
            if truncated:
                break
            for member in clip.members:
                member_duration = member.end_ms - member.start_ms
                if member_duration <= 0:
                    # Defensive: skip zero/negative spans that would trip
                    # the SceneClipSpec end_ms > start_ms validator.
                    continue

                # If this member would push the timeline past the 5-min cap,
                # truncate it to fit and stop emitting.
                if timeline_cursor_ms + member_duration > max_total_ms:
                    allowed = max_total_ms - timeline_cursor_ms
                    if allowed <= 0:
                        truncated = True
                        break
                    adjusted_end = member.start_ms + allowed
                    if adjusted_end <= member.start_ms:
                        truncated = True
                        break
                    scene_clips.append(
                        SceneClipSpec(
                            scene_id=member.scene_id,
                            video_id=req.video_id,
                            source_type="gdrive",  # v2: source-detect from drive_files
                            start_ms=member.start_ms,
                            end_ms=adjusted_end,
                            timeline_start_ms=timeline_cursor_ms,
                        )
                    )
                    timeline_cursor_ms += allowed
                    truncated = True
                    break

                scene_clips.append(
                    SceneClipSpec(
                        scene_id=member.scene_id,
                        video_id=req.video_id,
                        source_type="gdrive",  # v2: source-detect from drive_files
                        start_ms=member.start_ms,
                        end_ms=member.end_ms,
                        timeline_start_ms=timeline_cursor_ms,
                    )
                )
                timeline_cursor_ms += member_duration

        return CompositionSpec(
            output=OutputSpec(),  # default 9:16 720p
            scene_clips=scene_clips,
            subtitles=[],
            transitions=[],
        )
