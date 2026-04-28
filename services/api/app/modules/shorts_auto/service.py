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
from heimdex_media_contracts.scenes.schemas import SceneDocument
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


def _resolve_member_transcript(
    scene_id: str,
    scenes_by_id: dict[str, SceneDocument] | None,
    speaker_transcripts: dict[str, str] | None,
) -> tuple[str | None, str | None]:
    """Pick the best available transcript + scene_caption for a clip member.

    Population priority for transcript:
      1. ``speaker_transcript`` (preferred — speaker-diarized)
      2. ``transcript_norm`` (normalized whisper output)
      3. ``transcript_raw`` (raw whisper output)

    Whitespace-only strings are treated as missing — STT can emit padding
    or BOMs that pass the truthy check but are visually empty. Strip
    each candidate before the ``or`` chain so a blank ``transcript_norm``
    doesn't shadow a real ``transcript_raw``.

    Empty strings collapse to ``None`` so the API response stays compact
    and the frontend can use truthy checks.
    """
    scene = (scenes_by_id or {}).get(scene_id)

    speaker = (speaker_transcripts or {}).get(scene_id)
    if speaker and speaker.strip():
        transcript: str | None = speaker
    elif scene is None:
        transcript = None
    else:
        norm = (scene.transcript_norm or "").strip()
        raw = (scene.transcript_raw or "").strip()
        transcript = norm or raw or None

    caption = scene.scene_caption if scene is not None else None
    if caption is not None and not caption.strip():
        caption = None
    return transcript, caption


def _member_to_response(
    m: ClipMember,
    *,
    scenes_by_id: dict[str, SceneDocument] | None = None,
    speaker_transcripts: dict[str, str] | None = None,
) -> ClipMemberResponse:
    transcript, scene_caption = _resolve_member_transcript(
        m.scene_id, scenes_by_id, speaker_transcripts,
    )
    return ClipMemberResponse(
        scene_id=m.scene_id,
        start_ms=m.start_ms,
        end_ms=m.end_ms,
        score=m.score,
        transcript=transcript,
        scene_caption=scene_caption,
    )


def _auto_clip_to_response(
    clip: AutoClip,
    *,
    scenes_by_id: dict[str, SceneDocument] | None = None,
    speaker_transcripts: dict[str, str] | None = None,
) -> AutoClipResponse:
    return AutoClipResponse(
        scene_ids=clip.scene_ids,
        members=[
            _member_to_response(
                m,
                scenes_by_id=scenes_by_id,
                speaker_transcripts=speaker_transcripts,
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
        candidates = await self.selector.fetch_candidates(
            org_id=org_id,
            video_id=req.video_id,
            mode=contract_mode,
            person_cluster_id=req.person_cluster_id,
        )
        scenes = candidates.scenes
        if not scenes:
            return _empty_response(req, "no_candidate_scenes_after_filter")
        scenes_by_id = {s.scene_id: s for s in scenes}

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

        clip_responses = [
            _auto_clip_to_response(
                c,
                scenes_by_id=scenes_by_id,
                speaker_transcripts=candidates.speaker_transcripts,
            )
            for c in clips
        ]
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
        """Render ONE clip as one short. Two paths:

        1. Explicit ``scene_ids`` — render exactly those scenes in the
           order supplied. Used by the per-clip render buttons in the
           UI. Skips auto-select entirely.
        2. No ``scene_ids`` — run auto-select, render the top-scoring
           clip. Historical back-to-back-all-clips concatenation is
           gone; each render is ONE short.
        """
        if req.auto_caption:
            # Auto-caption is P4. Reject explicitly so callers get a
            # clean signal instead of silently dropping the flag.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="auto_caption is not yet enabled (deferred to phase 4)",
            )

        if req.scene_ids:
            clip = await self._build_clip_from_scene_ids(
                org_id=org_id,
                video_id=req.video_id,
                scene_ids=req.scene_ids,
            )
        else:
            clip = await self._select_top_clip(org_id, user_id, req)

        if clip is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="no scenes available to render",
            )

        composition = self._compose_single_clip(req, clip)
        title = req.title or f"Auto {req.mode.value} ({len(clip.members)} scenes)"
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
            scene_count=len(clip.members),
            source="scene_ids" if req.scene_ids else "top_clip",
        )
        return await self.shorts_render_service.create_render_job(
            org_id=org_id,
            user_id=user_id,
            payload=payload,
        )

    async def _build_clip_from_scene_ids(
        self,
        *,
        org_id: UUID,
        video_id: str,
        scene_ids: list[str],
    ) -> AutoClipResponse | None:
        """Look up specific scenes by id + compose them into one clip.

        Preserves the caller-supplied scene_id order (scene_ids passed
        are the definitive ordering). Skips auto-select — client knows
        which scenes they want. Returns None when zero lookups hit.
        """
        # Reuse the selector's OS client; a no-mode fetch would return
        # nothing, so we query by video_id + filter to the requested
        # scene_ids client-side. Small corpus, simple.
        from heimdex_media_contracts.shorts.scorer import ScoringMode

        # Fetch all scenes for this video (scoped) then pick the matching ids.
        candidates = await self.selector.fetch_candidates(
            org_id=org_id,
            video_id=video_id,
            mode=ScoringMode.BOTH,
        )
        by_id = {s.scene_id: s for s in candidates.scenes}
        ordered = [by_id[sid] for sid in scene_ids if sid in by_id]
        if not ordered:
            return None

        members = [
            _member_to_response(
                ClipMember(
                    scene_id=s.scene_id,
                    start_ms=s.start_ms,
                    end_ms=s.end_ms,
                    score=1.0,  # user selected them; score is moot
                ),
                scenes_by_id=by_id,
                speaker_transcripts=candidates.speaker_transcripts,
            )
            for s in ordered
        ]
        scene_id_list = [m.scene_id for m in members]
        total_ms = sum(m.end_ms - m.start_ms for m in members)
        indices = sorted(s.index for s in ordered)
        is_continuous = all(
            indices[i + 1] - indices[i] == 1 for i in range(len(indices) - 1)
        )
        return AutoClipResponse(
            scene_ids=scene_id_list,
            members=members,
            start_ms=members[0].start_ms,
            end_ms=members[-1].end_ms,
            duration_ms=total_ms,
            score=1.0,
            reasons=[],
            is_continuous=is_continuous,
        )

    async def _select_top_clip(
        self,
        org_id: UUID,
        user_id: UUID,
        req: AutoRenderRequest,
    ) -> AutoClipResponse | None:
        """Run auto-select and return the first (top-scoring) clip only."""
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
        if not selection.clips:
            return None
        return selection.clips[0]

    def _compose_single_clip(
        self,
        req: AutoRenderRequest,
        clip: AutoClipResponse,
    ) -> CompositionSpec:
        """Build a CompositionSpec from ONE clip's members.

        One SceneClipSpec per ``ClipMemberResponse`` so each span stays
        inside its named scene's bounds (required by
        ``ShortsRenderService._validate_scene_clips``). Members are
        packed back-to-back on the composition timeline in the
        caller-supplied order. ``CompositionSpec._validate_max_duration``
        enforces a 5-min hard cap; we trim the trailing member's
        ``end_ms`` to fit rather than dropping scenes silently.
        """
        scene_clips: list[SceneClipSpec] = []
        timeline_cursor_ms = 0
        max_total_ms = 5 * 60 * 1000  # mirrors composition.schemas cap

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
                    break
                adjusted_end = member.start_ms + allowed
                if adjusted_end <= member.start_ms:
                    break
                scene_clips.append(
                    SceneClipSpec(
                        scene_id=member.scene_id,
                        video_id=req.video_id,
                        source_type="gdrive",
                        start_ms=member.start_ms,
                        end_ms=adjusted_end,
                        timeline_start_ms=timeline_cursor_ms,
                    )
                )
                timeline_cursor_ms += allowed
                break

            scene_clips.append(
                SceneClipSpec(
                    scene_id=member.scene_id,
                    video_id=req.video_id,
                    source_type="gdrive",
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
