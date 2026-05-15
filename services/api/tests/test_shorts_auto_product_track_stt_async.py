"""Async tests for the track_stt pipeline with mocked clients.

Covers the I/O-bound portions: BM25 OS query, gpt-4o-mini chunk
scoring, and the end-to-end service orchestration.

Strategy: every external dep (AsyncOpenSearch, AsyncOpenAI,
render-enqueue callable) is a fake constructed in this file. No
network. No DB. Tests run in <100ms total.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.shorts_auto_product.track_stt import (
    chunk_scorer,
    mention_extractor,
    service,
)
from app.modules.shorts_auto_product.track_stt.errors import (
    LiveBlockTooShortError,
    MentionExtractionError,
    NoMentionsFoundError,
    SttPipelineError,
    TranscriptUnavailableError,
)
from app.modules.shorts_auto_product.track_stt.models import (
    ChunkScore,
    MentionedScene,
    MentionSegment,
    ScoredChunk,
)


# ---------- fake OpenSearch ----------


class _FakeOSClient:
    def __init__(self, *, hits: list[dict[str, Any]] | None = None, raises: Exception | None = None):
        self._hits = hits or []
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    async def search(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"index": index, "body": body})
        if self._raises is not None:
            raise self._raises
        return {"hits": {"total": {"value": len(self._hits)}, "hits": self._hits}}


def _hit(scene_id: str, start_ms: int, end_ms: int, transcript: str = "", caption: str = "", score: float = 1.0):
    return {
        "_score": score,
        "_source": {
            "scene_id": scene_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "transcript_raw": transcript,
            "scene_caption": caption,
        },
    }


# ---------- fake AsyncOpenAI ----------


@dataclass
class _Usage:
    prompt_tokens: int = 700
    completion_tokens: int = 50


@dataclass
class _Message:
    content: str


@dataclass
class _Choice:
    message: _Message


@dataclass
class _Response:
    choices: list[_Choice]
    usage: _Usage = field(default_factory=_Usage)


class _FakeChatCompletions:
    def __init__(self, *, raw_text: str | None = None, raises: Exception | None = None):
        self._raw = raw_text
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _Response:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        text = self._raw if self._raw is not None else json.dumps({"scores": [{"hook_score": 0.7, "has_cta": False, "importance_score": 0.8}]})
        return _Response(choices=[_Choice(message=_Message(content=text))])


class _FakeOpenAI:
    def __init__(self, *, raw_text: str | None = None, raises: Exception | None = None):
        self.completions = _FakeChatCompletions(raw_text=raw_text, raises=raises)
        self.chat = _ChatNs(self.completions)


class _ChatNs:
    def __init__(self, completions: _FakeChatCompletions):
        self.completions = completions


# ============================================================
# mention_extractor.find_mentioned_scenes
# ============================================================


class TestMentionExtractor:
    @pytest.mark.asyncio
    async def test_returns_empty_when_no_hits(self):
        os_client = _FakeOSClient(hits=[])
        result = await mention_extractor.find_mentioned_scenes(
            os_client=os_client,
            index_alias="heimdex_scenes",
            org_id=uuid4(),
            video_id="gd_x",
            llm_label="달심",
            spoken_aliases=[],
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_scenes_with_correct_shape(self):
        org = uuid4()
        os_client = _FakeOSClient(
            hits=[
                _hit("gd_x_scene_001", 0, 5_000, transcript="달심 제품을 보여드리면", score=2.5),
                _hit("gd_x_scene_002", 5_000, 10_000, transcript="이 주스는 정말 좋습니다", score=1.8),
            ],
        )
        result = await mention_extractor.find_mentioned_scenes(
            os_client=os_client,
            index_alias="heimdex_scenes",
            org_id=org,
            video_id="gd_x",
            llm_label="달심",
            spoken_aliases=["이 주스"],
        )
        assert len(result) == 2
        assert all(isinstance(s, MentionedScene) for s in result)
        # Org filter present in must clauses (cross-org leakage guard).
        body = os_client.calls[0]["body"]
        assert {"term": {"org_id": str(org)}} in body["query"]["bool"]["must"]
        assert {"term": {"video_id": "gd_x"}} in body["query"]["bool"]["must"]

    @pytest.mark.asyncio
    async def test_os_failure_wraps_as_extraction_error(self):
        os_client = _FakeOSClient(raises=RuntimeError("connection refused"))
        with pytest.raises(MentionExtractionError, match="OS search failed"):
            await mention_extractor.find_mentioned_scenes(
                os_client=os_client,
                index_alias="heimdex_scenes",
                org_id=uuid4(),
                video_id="gd_x",
                llm_label="달심",
                spoken_aliases=[],
            )


# ============================================================
# chunk_scorer.score_segment_chunks
# ============================================================


def _make_segment(*, num_scenes: int = 2, scene_duration_ms: int = 15_000, transcript_prefix: str = "speech") -> MentionSegment:
    scenes = [
        MentionedScene(
            scene_id=f"scene_{i:03d}",
            start_ms=i * scene_duration_ms,
            end_ms=(i + 1) * scene_duration_ms,
            score=1.0,
            matched_field="transcript_raw",
            matched_aliases=[],
            transcript_text=f"{transcript_prefix} {i}",
            caption_text="",
        )
        for i in range(num_scenes)
    ]
    return MentionSegment(
        start_ms=0,
        end_ms=num_scenes * scene_duration_ms,
        scenes=scenes,
    )


class TestChunkScorer:
    @pytest.mark.asyncio
    async def test_happy_path_returns_one_score_per_chunk(self):
        seg = _make_segment(num_scenes=2, scene_duration_ms=15_000)
        # 30s segment, default chunk size 20s → 2 chunks (0-20, 20-30).
        openai = _FakeOpenAI(
            raw_text=json.dumps({
                "scores": [
                    {"hook_score": 0.7, "has_cta": False, "importance_score": 0.8},
                    {"hook_score": 0.3, "has_cta": True, "importance_score": 0.5},
                ]
            })
        )
        result = await chunk_scorer.score_segment_chunks(
            segment=seg, openai_client=openai,
        )
        assert len(result) == 2
        assert result[0].score.hook_score == 0.7
        assert result[1].score.has_cta is True

    @pytest.mark.asyncio
    async def test_empty_segment_returns_empty(self):
        seg = MentionSegment(start_ms=0, end_ms=0, scenes=[])
        openai = _FakeOpenAI()
        result = await chunk_scorer.score_segment_chunks(
            segment=seg, openai_client=openai,
        )
        assert result == []

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_heuristic(self):
        """A network failure must NOT surface as an exception. Each
        chunk gets a 0.5/False/0.5 baseline so the pipeline still
        produces output. This is the contract that lets the wizard
        keep working when the LLM API is degraded.
        """
        seg = _make_segment(num_scenes=1, scene_duration_ms=25_000)
        openai = _FakeOpenAI(raises=RuntimeError("openai down"))
        result = await chunk_scorer.score_segment_chunks(
            segment=seg, openai_client=openai,
        )
        assert len(result) >= 1
        for chunk in result:
            assert chunk.score.hook_score == 0.5
            assert chunk.score.has_cta is False
            assert chunk.score.importance_score == 0.5

    @pytest.mark.asyncio
    async def test_count_mismatch_falls_back_to_heuristic(self):
        """LLM returned wrong number of scores — fallback to heuristic
        rather than fail. We send N chunks; expect N scores.
        """
        seg = _make_segment(num_scenes=2, scene_duration_ms=15_000)
        # Send 1 score for 2 chunks.
        openai = _FakeOpenAI(
            raw_text=json.dumps({"scores": [{"hook_score": 0.9, "has_cta": True, "importance_score": 0.9}]})
        )
        result = await chunk_scorer.score_segment_chunks(
            segment=seg, openai_client=openai,
        )
        assert len(result) == 2
        # All heuristic now.
        for chunk in result:
            assert chunk.score.hook_score == 0.5

    @pytest.mark.asyncio
    async def test_invalid_json_falls_back_to_heuristic(self):
        seg = _make_segment(num_scenes=1, scene_duration_ms=25_000)
        openai = _FakeOpenAI(raw_text="this is not json")
        result = await chunk_scorer.score_segment_chunks(
            segment=seg, openai_client=openai,
        )
        for chunk in result:
            assert chunk.score.hook_score == 0.5

    @pytest.mark.asyncio
    async def test_caption_used_when_transcript_empty(self):
        """gd_bb9c22c2c00d180c-style: transcript_raw is "" but
        scene_caption is populated. Chunk scorer must still get text
        (from the caption) so the LLM has something to score.
        """
        scene = MentionedScene(
            scene_id="x",
            start_ms=0,
            end_ms=25_000,
            score=1.0,
            matched_field="scene_caption",
            matched_aliases=[],
            transcript_text="",  # empty — caption-only video
            caption_text="호스트가 샴푸를 소개하고 있다",
        )
        seg = MentionSegment(start_ms=0, end_ms=25_000, scenes=[scene])
        openai = _FakeOpenAI(
            raw_text=json.dumps({"scores": [{"hook_score": 0.5, "has_cta": False, "importance_score": 0.6}]})
        )
        result = await chunk_scorer.score_segment_chunks(
            segment=seg, openai_client=openai,
        )
        # 25s scene at default 20s chunk size → 2 chunks (the second
        # is a 5s tail). What matters for this test is that the
        # caption text propagated to every chunk's ``text`` field.
        assert len(result) >= 1
        for chunk in result:
            assert "샴푸" in chunk.text


# ============================================================
# service.assemble_stt_clip end-to-end
# ============================================================


class TestServiceEndToEnd:
    @pytest.mark.asyncio
    async def test_happy_path_returns_render_job_id(self):
        # 3 mentioned scenes spanning 30s → 1 segment → at least 1
        # chunk → 1 selected chunk → 1 composition → 1 render id.
        os_client = _FakeOSClient(
            hits=[
                _hit("scene_001", 0, 10_000, transcript="달심 ABC 주스", score=3.0),
                _hit("scene_002", 10_000, 20_000, transcript="이 주스는 정말 좋습니다", score=2.0),
                _hit("scene_003", 20_000, 30_000, transcript="달심 함께 해주세요", score=2.5),
            ],
        )
        openai = _FakeOpenAI(
            raw_text=json.dumps({"scores": [{"hook_score": 0.7, "has_cta": False, "importance_score": 0.9}, {"hook_score": 0.5, "has_cta": True, "importance_score": 0.7}]})
        )

        captured_specs: list[Any] = []
        expected_render_id = uuid4()

        async def _enqueue(spec):
            captured_specs.append(spec)
            return expected_render_id

        result = await service.assemble_stt_clip(
            org_id=uuid4(),
            catalog_entry_id=uuid4(),
            llm_label="달심",
            spoken_aliases=["이 주스"],
            os_video_id="gd_x",
            target_duration_ms=30_000,
            title="test",
            os_client=os_client,
            openai_client=openai,
            enqueue_render=_enqueue,
        )
        assert result.render_job_id == expected_render_id
        assert result.mentioned_scene_count == 3
        assert len(captured_specs) == 1
        assert captured_specs[0].title == "test"
        assert captured_specs[0].clip_count >= 1

    @pytest.mark.asyncio
    async def test_no_mentions_raises_no_mentions_found(self):
        os_client = _FakeOSClient(hits=[])
        openai = _FakeOpenAI()
        async def _enqueue(spec): return uuid4()  # noqa: E306

        with pytest.raises(NoMentionsFoundError):
            await service.assemble_stt_clip(
                org_id=uuid4(),
                catalog_entry_id=uuid4(),
                llm_label="달심",
                spoken_aliases=[],
                os_video_id="gd_x",
                target_duration_ms=30_000,
                title=None,
                os_client=os_client,
                openai_client=openai,
                enqueue_render=_enqueue,
            )

    @pytest.mark.asyncio
    async def test_mentions_but_no_text_raises_transcript_unavailable(self):
        # OS hit, but every scene has empty transcript AND empty caption.
        # This is a pathological state for malformed OS docs.
        os_client = _FakeOSClient(
            hits=[_hit("scene_001", 0, 25_000, transcript="", caption="")],
        )
        openai = _FakeOpenAI()
        async def _enqueue(spec): return uuid4()  # noqa: E306

        with pytest.raises(TranscriptUnavailableError):
            await service.assemble_stt_clip(
                org_id=uuid4(),
                catalog_entry_id=uuid4(),
                llm_label="달심",
                spoken_aliases=[],
                os_video_id="gd_x",
                target_duration_ms=30_000,
                title=None,
                os_client=os_client,
                openai_client=openai,
                enqueue_render=_enqueue,
            )

    @pytest.mark.asyncio
    async def test_too_short_for_segment_raises_no_mentions(self):
        # Only 5s of mentions (below MIN_SEGMENT_MS=20s).
        os_client = _FakeOSClient(
            hits=[_hit("scene_001", 0, 5_000, transcript="달심", score=1.0)],
        )
        openai = _FakeOpenAI()
        async def _enqueue(spec): return uuid4()  # noqa: E306

        with pytest.raises(NoMentionsFoundError, match="segment"):
            await service.assemble_stt_clip(
                org_id=uuid4(),
                catalog_entry_id=uuid4(),
                llm_label="달심",
                spoken_aliases=[],
                os_video_id="gd_x",
                target_duration_ms=30_000,
                title=None,
                os_client=os_client,
                openai_client=openai,
                enqueue_render=_enqueue,
            )

    @pytest.mark.asyncio
    async def test_render_enqueue_failure_wraps_as_pipeline_error(self):
        os_client = _FakeOSClient(
            hits=[
                _hit("scene_001", 0, 15_000, transcript="달심 ABC 주스"),
                _hit("scene_002", 15_000, 30_000, transcript="달심"),
            ],
        )
        openai = _FakeOpenAI()
        async def _enqueue(spec):  # noqa: E306
            raise RuntimeError("render service down")

        with pytest.raises(SttPipelineError, match="render enqueue failed"):
            await service.assemble_stt_clip(
                org_id=uuid4(),
                catalog_entry_id=uuid4(),
                llm_label="달심",
                spoken_aliases=[],
                os_video_id="gd_x",
                target_duration_ms=30_000,
                title=None,
                os_client=os_client,
                openai_client=openai,
                enqueue_render=_enqueue,
            )

    @pytest.mark.asyncio
    async def test_caption_only_video_still_produces_clip(self):
        """gd_bb9c22c2c00d180c-style: every scene has empty
        transcript_raw but populated scene_caption. Pipeline must
        still produce a valid clip from caption-only signal.
        """
        os_client = _FakeOSClient(
            hits=[
                _hit("scene_001", 0, 15_000, transcript="", caption="호스트가 샴푸를 소개하고 있다"),
                _hit("scene_002", 15_000, 30_000, transcript="", caption="호스트가 샴푸 사용법을 설명한다"),
            ],
        )
        openai = _FakeOpenAI()
        captured: list[UUID] = []

        async def _enqueue(spec):
            rid = uuid4()
            captured.append(rid)
            return rid

        result = await service.assemble_stt_clip(
            org_id=uuid4(),
            catalog_entry_id=uuid4(),
            llm_label="샴푸",
            spoken_aliases=[],
            os_video_id="gd_bb9c",
            target_duration_ms=30_000,
            title=None,
            os_client=os_client,
            openai_client=openai,
            enqueue_render=_enqueue,
        )
        assert result.render_job_id == captured[0]
        assert result.fallback_used == "none"


# ---------- storyboard mode wiring ----------


class TestServiceStoryboardWiring:
    """Service.py picks the right composition path based on whether
    a storyboard picker is supplied. Failures in the picker fall
    back cleanly to the legacy clip_selector path so a render
    always completes when there's enough chunk data.
    """

    def _two_scene_os_client(self) -> _FakeOSClient:
        return _FakeOSClient(
            hits=[
                _hit("scene_001", 0, 15_000, transcript="달심 이거 진짜 좋아요"),
                _hit("scene_002", 15_000, 30_000, transcript="달심 가격도 좋고"),
            ],
        )

    @pytest.mark.asyncio
    async def test_legacy_path_when_picker_is_none(self) -> None:
        # No picker → legacy clip_selector → composition_builder
        # gets chunks (not a storyboard). The CompositionSpec
        # contains scene_clips but no subtitles (post-2026-05-07
        # default). This is the regression check that picker=None
        # leaves the existing code path untouched.
        os_client = self._two_scene_os_client()
        openai = _FakeOpenAI()
        captured: list[Any] = []

        async def _enqueue(spec):
            captured.append(spec)
            return uuid4()

        await service.assemble_stt_clip(
            org_id=uuid4(),
            catalog_entry_id=uuid4(),
            llm_label="달심",
            spoken_aliases=[],
            os_video_id="gd_x",
            target_duration_ms=30_000,
            title="t",
            os_client=os_client,
            openai_client=openai,
            enqueue_render=_enqueue,
            storyboard_picker=None,
        )
        assert len(captured) == 1
        spec = captured[0]
        assert len(spec.scene_clips) >= 1
        assert spec.subtitles == []

    @pytest.mark.asyncio
    async def test_storyboard_picker_drives_composition_when_supplied(self) -> None:
        # When a picker is wired in, the composition spec's
        # scene_clips MUST come from the picker's fragments — not
        # the legacy contiguous window. We verify by handing in a
        # fake picker that returns a known fragment range and
        # asserting the resulting scene_clips correspond.
        from app.modules.shorts_auto_product.track_stt.storyboard import (
            SlotRole,
            StoryboardFragment,
            StoryboardPlan,
        )

        os_client = self._two_scene_os_client()
        openai = _FakeOpenAI()
        captured: list[Any] = []

        async def _enqueue(spec):
            captured.append(spec)
            return uuid4()

        class _StubPicker:
            async def assemble(self, **kwargs):
                # Return a single HOOK fragment in the FIRST scene,
                # 0-8s. The legacy clip_selector would normally pick
                # all 30s; if storyboard wins, scene_clips will be
                # exactly the 8s slice.
                score = ChunkScore(
                    hook_score=0.9, has_cta=False, importance_score=0.5,
                )
                return StoryboardPlan(
                    fragments=[
                        StoryboardFragment(
                            role=SlotRole.HOOK,
                            source_start_ms=0,
                            source_end_ms=8_000,
                            target_duration_ms=8_000,
                            chunk_score=score,
                            rationale="test:hook",
                        ),
                    ],
                    total_duration_ms=8_000,
                    slots_filled={SlotRole.HOOK},
                    fallbacks_used=[],
                )

        await service.assemble_stt_clip(
            org_id=uuid4(),
            catalog_entry_id=uuid4(),
            llm_label="달심",
            spoken_aliases=[],
            os_video_id="gd_x",
            target_duration_ms=30_000,
            title="t",
            os_client=os_client,
            openai_client=openai,
            enqueue_render=_enqueue,
            storyboard_picker=_StubPicker(),
        )
        spec = captured[0]
        # Storyboard fragment 0-8000ms is fully inside scene_001;
        # exactly one SceneClipSpec emitted.
        assert len(spec.scene_clips) == 1
        assert spec.scene_clips[0].start_ms == 0
        assert spec.scene_clips[0].end_ms == 8_000
        assert spec.scene_clips[0].scene_id == "scene_001"

    @pytest.mark.asyncio
    async def test_storyboard_picker_failure_falls_back_to_legacy(self) -> None:
        # If the picker raises, service.py logs and falls back to
        # the legacy clip_selector path so a render still gets out.
        # Critical for prod safety — no picker bug should ever drop
        # a real wizard request.
        os_client = self._two_scene_os_client()
        openai = _FakeOpenAI()
        captured: list[Any] = []

        async def _enqueue(spec):
            captured.append(spec)
            return uuid4()

        class _BoomPicker:
            async def assemble(self, **kwargs):
                raise RuntimeError("picker exploded")

        await service.assemble_stt_clip(
            org_id=uuid4(),
            catalog_entry_id=uuid4(),
            llm_label="달심",
            spoken_aliases=[],
            os_video_id="gd_x",
            target_duration_ms=30_000,
            title="t",
            os_client=os_client,
            openai_client=openai,
            enqueue_render=_enqueue,
            storyboard_picker=_BoomPicker(),
        )
        # Render still happened — picker failure didn't propagate.
        assert len(captured) == 1
        spec = captured[0]
        # Legacy path → scene_clips span the full window picked
        # by clip_selector, not just an 8s storyboard slice.
        total_clip_duration = sum(
            c.end_ms - c.start_ms for c in spec.scene_clips
        )
        assert total_clip_duration > 8_000

    @pytest.mark.asyncio
    async def test_storyboard_shadow_mode_emits_diff_but_uses_legacy(self) -> None:
        # Shadow mode runs the picker AND the legacy selector,
        # logs a diff event for telemetry, but the LEGACY plan is
        # what produces the actual render. Validates Tier B output
        # against ground-truth before flipping the real switch.
        from app.modules.shorts_auto_product.track_stt.storyboard import (
            SlotRole,
            StoryboardFragment,
            StoryboardPlan,
        )

        os_client = self._two_scene_os_client()
        openai = _FakeOpenAI()
        captured: list[Any] = []

        async def _enqueue(spec):
            captured.append(spec)
            return uuid4()

        score = ChunkScore(
            hook_score=0.9, has_cta=False, importance_score=0.5,
        )

        class _StubPicker:
            assemble_calls = 0

            async def assemble(self, **kwargs):
                _StubPicker.assemble_calls += 1
                return StoryboardPlan(
                    fragments=[
                        StoryboardFragment(
                            role=SlotRole.HOOK,
                            source_start_ms=0,
                            source_end_ms=8_000,
                            target_duration_ms=8_000,
                            chunk_score=score,
                            rationale="shadow",
                        ),
                    ],
                    total_duration_ms=8_000,
                    slots_filled={SlotRole.HOOK},
                    fallbacks_used=[],
                )

        await service.assemble_stt_clip(
            org_id=uuid4(),
            catalog_entry_id=uuid4(),
            llm_label="달심",
            spoken_aliases=[],
            os_video_id="gd_x",
            target_duration_ms=30_000,
            title="t",
            os_client=os_client,
            openai_client=openai,
            enqueue_render=_enqueue,
            storyboard_picker=_StubPicker(),
            storyboard_shadow_mode=True,
        )
        # Picker DID run (shadow mode logs the diff)…
        assert _StubPicker.assemble_calls == 1
        # …but the rendered scene_clips come from LEGACY, so total
        # duration is bigger than the 8s storyboard would produce.
        spec = captured[0]
        total_clip_duration = sum(
            c.end_ms - c.start_ms for c in spec.scene_clips
        )
        assert total_clip_duration > 8_000


# ============================================================
# Phase 1 live-only filter — mention_extractor allowlist + service
# ============================================================


def _seg_hit(
    scene_id: str,
    start_ms: int,
    end_ms: int,
    *,
    speaker_transcript: str = "",
    speech_segment_count: int = 0,
) -> dict[str, Any]:
    """OS hit shape returned by the segmentation pre-fetch in
    ``service._fetch_scenes_for_segmentation``. Distinct from the
    BM25 ``_hit`` helper so a test fixture makes its intent obvious.
    """
    return {
        "_source": {
            "scene_id": scene_id,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "speaker_transcript": speaker_transcript,
            "transcript_raw": "",
            "speech_segment_count": speech_segment_count,
        },
    }


class _RoutedOSClient:
    """Fake OS client that routes responses based on the query body.

    The Phase 1 live-only path issues TWO different OS queries:
      1. Segmentation pre-fetch — filter-only query, ``_source``
         includes ``speech_segment_count``.
      2. BM25 mention extraction — bool query with ``must`` clauses.

    The plain ``_FakeOSClient`` returns the same hits for both, which
    would mask whether the segmentation step ran. This fake routes by
    inspecting the body's ``_source`` field to decide which canned
    response to return.
    """

    def __init__(
        self,
        *,
        seg_hits: list[dict[str, Any]] | None = None,
        bm25_hits: list[dict[str, Any]] | None = None,
    ):
        self._seg_hits = seg_hits or []
        self._bm25_hits = bm25_hits or []
        self.calls: list[dict[str, Any]] = []
        self.seg_call_count = 0
        self.bm25_call_count = 0

    async def search(self, *, index: str, body: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"index": index, "body": body})
        source = body.get("_source") or []
        if "speech_segment_count" in source:
            self.seg_call_count += 1
            hits = self._seg_hits
        else:
            self.bm25_call_count += 1
            hits = self._bm25_hits
        return {"hits": {"total": {"value": len(hits)}, "hits": hits}}


class TestMentionExtractorAllowlist:
    """Allowlist filtering — the API change paired with the service's
    live-block pre-step. Independent unit coverage so a regression
    here surfaces without needing to run the full pipeline.
    """

    @pytest.mark.asyncio
    async def test_allowlist_none_is_passthrough(self):
        """Back-compat: None preserves today's behavior."""
        os_client = _FakeOSClient(
            hits=[
                _hit("scene_001", 0, 5_000, transcript="달심", score=2.0),
                _hit("scene_002", 5_000, 10_000, transcript="달심", score=1.5),
            ],
        )
        result = await mention_extractor.find_mentioned_scenes(
            os_client=os_client,
            index_alias="heimdex_scenes",
            org_id=uuid4(),
            video_id="gd_x",
            llm_label="달심",
            spoken_aliases=[],
            scene_id_allowlist=None,
        )
        assert {s.scene_id for s in result} == {"scene_001", "scene_002"}

    @pytest.mark.asyncio
    async def test_allowlist_filters_hits(self):
        """Hits whose scene_id is not in the allowlist are dropped."""
        os_client = _FakeOSClient(
            hits=[
                _hit("live_001", 0, 5_000, transcript="달심", score=2.0),
                _hit("silent_001", 5_000, 10_000, transcript="달심", score=1.5),
                _hit("live_002", 10_000, 15_000, transcript="달심", score=1.0),
            ],
        )
        result = await mention_extractor.find_mentioned_scenes(
            os_client=os_client,
            index_alias="heimdex_scenes",
            org_id=uuid4(),
            video_id="gd_x",
            llm_label="달심",
            spoken_aliases=[],
            scene_id_allowlist=frozenset({"live_001", "live_002"}),
        )
        # ``silent_001`` filtered out; relative order of survivors
        # preserved (OS already ranked them by score).
        assert [s.scene_id for s in result] == ["live_001", "live_002"]

    @pytest.mark.asyncio
    async def test_empty_allowlist_returns_empty(self):
        """``frozenset()`` is not the same as ``None`` — empty
        allowlist must drop everything (no live block found)."""
        os_client = _FakeOSClient(
            hits=[_hit("scene_001", 0, 5_000, transcript="달심", score=2.0)],
        )
        result = await mention_extractor.find_mentioned_scenes(
            os_client=os_client,
            index_alias="heimdex_scenes",
            org_id=uuid4(),
            video_id="gd_x",
            llm_label="달심",
            spoken_aliases=[],
            scene_id_allowlist=frozenset(),
        )
        assert result == []


class TestServiceLiveOnly:
    """End-to-end ``assemble_stt_clip`` with the Phase 1 flag on.

    The ``_RoutedOSClient`` proves the segmentation pre-fetch actually
    issued an OS query and the BM25 step received the resulting
    allowlist — together with the test assertions on
    ``seg_call_count`` / ``bm25_call_count`` this catches regressions
    where the flag is silently a no-op.
    """

    @pytest.mark.asyncio
    async def test_live_only_false_skips_segmentation_query(self):
        """Flag off → behavior identical to pre-Phase-1: a single
        OS round trip (BM25), no segmentation fetch.
        """
        os_client = _RoutedOSClient(
            bm25_hits=[
                _hit("scene_001", 0, 15_000, transcript="달심 좋아요"),
                _hit("scene_002", 15_000, 30_000, transcript="달심 가격"),
            ],
        )
        openai = _FakeOpenAI()

        async def _enqueue(spec):
            return uuid4()

        await service.assemble_stt_clip(
            org_id=uuid4(),
            catalog_entry_id=uuid4(),
            llm_label="달심",
            spoken_aliases=[],
            os_video_id="gd_x",
            target_duration_ms=30_000,
            title=None,
            os_client=os_client,
            openai_client=openai,
            enqueue_render=_enqueue,
            live_only=False,
        )
        assert os_client.seg_call_count == 0
        assert os_client.bm25_call_count == 1

    @pytest.mark.asyncio
    async def test_live_only_true_filters_mentions_to_live_block(self):
        """Flag on with two BM25 hits — one in the live block, one
        in the silent pre-roll. Only the live-block hit reaches the
        pipeline; pre-roll is dropped before scoring.
        """
        os_client = _RoutedOSClient(
            seg_hits=[
                # 0–10s: silent pre-roll (b-roll)
                _seg_hit("preroll_001", 0, 5_000),
                _seg_hit("preroll_002", 5_000, 10_000),
                # 10–40s: live host pitch (30s — enough to satisfy
                # target_duration_ms below)
                _seg_hit("live_001", 10_000, 25_000, speaker_transcript="달심 안녕", speech_segment_count=2),
                _seg_hit("live_002", 25_000, 40_000, speaker_transcript="달심 좋아요", speech_segment_count=3),
                # 40–50s: silent outro
                _seg_hit("outro_001", 40_000, 50_000),
            ],
            bm25_hits=[
                # Pre-roll match — must be dropped by the live filter
                _hit("preroll_001", 0, 5_000, transcript="달심 (OCR caption)", score=2.5),
                # Live matches — must survive
                _hit("live_001", 10_000, 25_000, transcript="달심 안녕", score=2.0),
                _hit("live_002", 25_000, 40_000, transcript="달심 좋아요", score=1.8),
            ],
        )
        openai = _FakeOpenAI(
            raw_text=json.dumps({"scores": [{"hook_score": 0.7, "has_cta": False, "importance_score": 0.9}]})
        )

        async def _enqueue(spec):
            return uuid4()

        result = await service.assemble_stt_clip(
            org_id=uuid4(),
            catalog_entry_id=uuid4(),
            llm_label="달심",
            spoken_aliases=[],
            os_video_id="gd_x",
            target_duration_ms=20_000,
            title=None,
            os_client=os_client,
            openai_client=openai,
            enqueue_render=_enqueue,
            live_only=True,
        )
        assert os_client.seg_call_count == 1
        assert os_client.bm25_call_count == 1
        # 3 BM25 hits, but only 2 survived (preroll_001 dropped).
        assert result.mentioned_scene_count == 2

    @pytest.mark.asyncio
    async def test_live_only_true_raises_when_block_too_short(self):
        """Flag on, live block exists but is shorter than the
        requested clip length — caller gets a friendly-failure
        ``LiveBlockTooShortError`` (NOT a generic pipeline error).
        """
        os_client = _RoutedOSClient(
            seg_hits=[
                _seg_hit("preroll_001", 0, 10_000),
                # 10s live block — caller wants 30s.
                _seg_hit(
                    "live_001",
                    10_000,
                    20_000,
                    speaker_transcript="달심",
                    speech_segment_count=1,
                ),
                _seg_hit("outro_001", 20_000, 30_000),
            ],
            bm25_hits=[_hit("live_001", 10_000, 20_000, transcript="달심")],
        )
        openai = _FakeOpenAI()

        async def _enqueue(spec):
            return uuid4()

        with pytest.raises(LiveBlockTooShortError, match="host commentary"):
            await service.assemble_stt_clip(
                org_id=uuid4(),
                catalog_entry_id=uuid4(),
                llm_label="달심",
                spoken_aliases=[],
                os_video_id="gd_x",
                target_duration_ms=30_000,
                title=None,
                os_client=os_client,
                openai_client=openai,
                enqueue_render=_enqueue,
                live_only=True,
            )
        # BM25 must NOT have been called — too-short check fires
        # before mention extraction would have run.
        assert os_client.seg_call_count == 1
        assert os_client.bm25_call_count == 0

    @pytest.mark.asyncio
    async def test_live_only_true_raises_when_no_live_blocks(self):
        """All-silent video (no STT signal anywhere) → live_total_ms
        is 0 < target → too-short error.
        """
        os_client = _RoutedOSClient(
            seg_hits=[
                _seg_hit("silent_001", 0, 10_000),
                _seg_hit("silent_002", 10_000, 20_000),
            ],
            bm25_hits=[_hit("silent_001", 0, 10_000, transcript="달심")],
        )
        openai = _FakeOpenAI()

        async def _enqueue(spec):
            return uuid4()

        with pytest.raises(LiveBlockTooShortError):
            await service.assemble_stt_clip(
                org_id=uuid4(),
                catalog_entry_id=uuid4(),
                llm_label="달심",
                spoken_aliases=[],
                os_video_id="gd_x",
                target_duration_ms=20_000,
                title=None,
                os_client=os_client,
                openai_client=openai,
                enqueue_render=_enqueue,
                live_only=True,
            )
