"""Unit-scope tests for the STT-first enumeration pipeline (PR 3).

Three layers covered:

* :mod:`enumerate_stt.transcript_loader` — pure async, OS mocked
* :mod:`enumerate_stt.llm_enumerator` — OpenAI mocked
* :mod:`enumerate_stt.service` — orchestrator with both mocked +
  catalog repo mocked

Run locally:

    cd services/api && source .venv/bin/activate && pytest \\
        tests/test_shorts_auto_product_enumerate_stt.py
"""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from heimdex_media_contracts.product import (
    TRANSCRIPT_ENUMERATION_PROMPT_VERSION,
)

from app.modules.shorts_auto_product.enumerate_stt.errors import (
    EnumerationLLMError,
    STTEnumerationError,
    TranscriptUnavailableError,
)
from app.modules.shorts_auto_product.enumerate_stt.llm_enumerator import (
    TranscriptEnumerationResult,
    TranscriptEnumerator,
    _estimate_cost_usd,
    _normalize_whitespace,
)
from app.modules.shorts_auto_product.enumerate_stt.service import (
    STT_ENUMERATION_VERSION,
    _build_dedup_term_set,
    _has_term_overlap,
    _normalize_term,
    _to_catalog_row,
    run_stt_enumeration,
)
from app.modules.shorts_auto_product.enumerate_stt.transcript_loader import (
    _format_timestamp,
    load_transcript,
)


# ---------- helpers ----------


def _hit(*, scene_id: str, start_ms: int, transcript_raw: str = ""):
    return {
        "_source": {
            "scene_id": scene_id,
            "start_ms": start_ms,
            "transcript_raw": transcript_raw,
        },
    }


def _os_response(hits: list[dict]) -> dict:
    return {"hits": {"hits": hits}}


def _make_os_mock(*, hits: list[dict]):
    os_client = MagicMock()
    os_client.search = AsyncMock(return_value=_os_response(hits))
    return os_client


# ======================================================================
# transcript_loader
# ======================================================================


class TestFormatTimestamp:
    def test_zero(self):
        assert _format_timestamp(0) == "[00:00]"

    def test_under_one_minute(self):
        assert _format_timestamp(45_000) == "[00:45]"

    def test_minute_boundary(self):
        assert _format_timestamp(60_000) == "[01:00]"

    def test_hour_plus_uses_extended_minutes(self):
        # Plan-locked: hours-long videos render as [mm:ss] with mm>=60
        # rather than [hh:mm:ss] — the LLM correctly interprets that.
        # Switching format would force a TranscriptEnumerationPrompt
        # version bump.
        assert _format_timestamp(7_653_000) == "[127:33]"

    def test_negative_treated_as_zero(self):
        assert _format_timestamp(-100) == "[00:00]"


class TestLoadTranscript:
    @pytest.mark.asyncio
    async def test_happy_path_orders_by_start_ms(self):
        # OS query specifies sort=start_ms asc, but the loader still
        # consumes hits in the order returned. The mock's ordering
        # exercises the contract.
        os_client = _make_os_mock(hits=[
            _hit(scene_id="s1", start_ms=0, transcript_raw="안녕하세요"),
            _hit(scene_id="s2", start_ms=5_000, transcript_raw="오늘 소개할 상품"),
            _hit(scene_id="s3", start_ms=10_000, transcript_raw="달심 주스입니다"),
        ])
        text, count = await load_transcript(
            os_client=os_client,
            index_alias="heimdex_scenes",
            org_id=uuid4(),
            video_id="gd_test",
            max_tokens=1000,
        )
        assert count == 3
        lines = text.split("\n")
        assert len(lines) == 3
        assert lines[0] == "[00:00] 안녕하세요"
        assert lines[1] == "[00:05] 오늘 소개할 상품"
        assert lines[2] == "[00:10] 달심 주스입니다"

    @pytest.mark.asyncio
    async def test_empty_transcript_scenes_filtered(self):
        os_client = _make_os_mock(hits=[
            _hit(scene_id="s1", start_ms=0, transcript_raw=""),
            _hit(scene_id="s2", start_ms=5_000, transcript_raw="실제 발화"),
            _hit(scene_id="s3", start_ms=10_000, transcript_raw="   "),  # whitespace-only
        ])
        text, count = await load_transcript(
            os_client=os_client,
            index_alias="heimdex_scenes",
            org_id=uuid4(),
            video_id="gd_test",
            max_tokens=1000,
        )
        assert count == 1
        assert text == "[00:05] 실제 발화"

    @pytest.mark.asyncio
    async def test_no_scenes_raises(self):
        os_client = _make_os_mock(hits=[])
        with pytest.raises(TranscriptUnavailableError):
            await load_transcript(
                os_client=os_client,
                index_alias="heimdex_scenes",
                org_id=uuid4(),
                video_id="gd_no_scenes",
                max_tokens=1000,
            )

    @pytest.mark.asyncio
    async def test_all_empty_transcripts_raises(self):
        os_client = _make_os_mock(hits=[
            _hit(scene_id="s1", start_ms=0, transcript_raw=""),
            _hit(scene_id="s2", start_ms=5_000, transcript_raw="  "),
        ])
        with pytest.raises(TranscriptUnavailableError):
            await load_transcript(
                os_client=os_client,
                index_alias="heimdex_scenes",
                org_id=uuid4(),
                video_id="gd_no_stt",
                max_tokens=1000,
            )

    @pytest.mark.asyncio
    async def test_truncation_drops_partial_lines(self):
        # max_tokens=10 → char_cap = 15 (10 * 1.5). The first line
        # "[00:00] AB" is 11 chars; with newline=12. Second line
        # "[00:05] CDEF" is 12; total 12+12=24 > 15. Second drops.
        # Only the first line should be kept.
        os_client = _make_os_mock(hits=[
            _hit(scene_id="s1", start_ms=0, transcript_raw="AB"),
            _hit(scene_id="s2", start_ms=5_000, transcript_raw="CDEF"),
        ])
        text, count = await load_transcript(
            os_client=os_client,
            index_alias="heimdex_scenes",
            org_id=uuid4(),
            video_id="gd_test",
            max_tokens=10,
        )
        # Only first line fits; partial-line truncation would corrupt
        # the timestamp marker the LLM relies on.
        assert count == 1
        assert text == "[00:00] AB"

    @pytest.mark.asyncio
    async def test_query_filters_by_org_and_video(self):
        os_client = _make_os_mock(hits=[
            _hit(scene_id="s1", start_ms=0, transcript_raw="x"),
        ])
        org_id = uuid4()
        await load_transcript(
            os_client=os_client,
            index_alias="heimdex_scenes",
            org_id=org_id,
            video_id="gd_alpha",
            max_tokens=1000,
        )
        body = os_client.search.await_args.kwargs["body"]
        must = body["query"]["bool"]["must"]
        assert {"term": {"org_id": str(org_id)}} in must
        assert {"term": {"video_id": "gd_alpha"}} in must
        assert body["sort"] == [{"start_ms": "asc"}]


# ======================================================================
# llm_enumerator
# ======================================================================


class TestNormalizeWhitespace:
    def test_collapses_internal_runs(self):
        assert _normalize_whitespace("hi    there") == "hi there"

    def test_collapses_newlines(self):
        assert _normalize_whitespace("a\nb\n  c") == "a b c"

    def test_strips_ends(self):
        assert _normalize_whitespace("  hello  ") == "hello"


class TestEstimateCostUsd:
    def test_no_usage_returns_zero(self):
        assert _estimate_cost_usd(None, "gpt-4o-mini") == 0.0

    def test_unknown_model_returns_zero(self):
        usage = SimpleNamespace(prompt_tokens=1000, completion_tokens=100)
        assert _estimate_cost_usd(usage, "unknown-model") == 0.0

    def test_gpt_4o_mini_pricing(self):
        # 1M input @ $0.15, 1M output @ $0.60 → $0.75 for 1M each
        usage = SimpleNamespace(
            prompt_tokens=1_000_000, completion_tokens=1_000_000,
        )
        cost = _estimate_cost_usd(usage, "gpt-4o-mini")
        assert cost == pytest.approx(0.75, abs=1e-9)


def _mock_openai_response(*, products: list[dict] | None = None,
                         model: str = "gpt-4o-mini",
                         prompt_tokens: int = 100,
                         completion_tokens: int = 50,
                         raw_content: str | None = None):
    """Build an OpenAI ChatCompletion-shaped mock response.

    When ``raw_content`` is given, it overrides ``products`` —
    used to simulate malformed JSON.
    """
    if raw_content is None:
        payload = {
            "products": products or [],
            "model": model,
            "prompt_version": "v1.0",
        }
        raw_content = json.dumps(payload)
    response = MagicMock()
    response.choices = [
        SimpleNamespace(message=SimpleNamespace(content=raw_content)),
    ]
    response.usage = SimpleNamespace(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
    )
    return response


def _make_openai_mock(*, response):
    client = MagicMock()
    client.chat = MagicMock()
    client.chat.completions = MagicMock()
    client.chat.completions.create = AsyncMock(return_value=response)
    return client


class TestTranscriptEnumerator:
    @pytest.mark.asyncio
    async def test_enumerate_happy_path(self):
        transcript = "[00:05] 오늘은 달심 주스를 39000원에 모시겠습니다"
        openai = _make_openai_mock(response=_mock_openai_response(
            products=[{
                "llm_label": "달심 주스",
                "spoken_aliases": ["달심", "주스"],
                "first_mention_ms": 5000,
                "example_quote": "오늘은 달심 주스를 39000원에 모시겠습니다",
                "confidence": 0.92,
            }],
        ))
        enumerator = TranscriptEnumerator(openai_client=openai)
        result = await enumerator.enumerate(transcript=transcript)
        assert isinstance(result, TranscriptEnumerationResult)
        assert len(result.products) == 1
        assert result.products[0].llm_label == "달심 주스"
        assert result.dropped_count == 0
        assert result.prompt_version == TRANSCRIPT_ENUMERATION_PROMPT_VERSION
        assert result.model == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_empty_transcript_raises(self):
        openai = _make_openai_mock(response=_mock_openai_response())
        enumerator = TranscriptEnumerator(openai_client=openai)
        with pytest.raises(EnumerationLLMError, match="empty"):
            await enumerator.enumerate(transcript="   ")
        # Defensive — caller should never get here, so we don't
        # spend tokens before bailing.
        openai.chat.completions.create.assert_not_called()

    @pytest.mark.asyncio
    async def test_openai_exception_wraps(self):
        client = MagicMock()
        client.chat = MagicMock()
        client.chat.completions = MagicMock()
        client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("rate limit"),
        )
        enumerator = TranscriptEnumerator(openai_client=client)
        with pytest.raises(EnumerationLLMError, match="OpenAI call failed"):
            await enumerator.enumerate(transcript="[00:00] x")

    @pytest.mark.asyncio
    async def test_malformed_json_wraps(self):
        openai = _make_openai_mock(response=_mock_openai_response(
            raw_content="not valid json {",
        ))
        enumerator = TranscriptEnumerator(openai_client=openai)
        with pytest.raises(EnumerationLLMError, match="schema validation"):
            await enumerator.enumerate(transcript="[00:00] x")

    @pytest.mark.asyncio
    async def test_quote_fidelity_drops_paraphrased(self):
        transcript = "[00:05] 진짜로 발화된 내용입니다"
        openai = _make_openai_mock(response=_mock_openai_response(
            products=[
                {
                    "llm_label": "real",
                    "spoken_aliases": ["real"],
                    "first_mention_ms": 5000,
                    "example_quote": "진짜로 발화된 내용입니다",  # exact match
                    "confidence": 0.9,
                },
                {
                    "llm_label": "ghost",
                    "spoken_aliases": ["ghost"],
                    "first_mention_ms": 8000,
                    "example_quote": "이것은 호스트가 한 적 없는 말입니다",  # not in transcript
                    "confidence": 0.8,
                },
            ],
        ))
        enumerator = TranscriptEnumerator(openai_client=openai)
        result = await enumerator.enumerate(transcript=transcript)
        assert len(result.products) == 1
        assert result.products[0].llm_label == "real"
        assert result.dropped_count == 1

    @pytest.mark.asyncio
    async def test_quote_fidelity_tolerates_whitespace_drift(self):
        # Transcript has a newline join; LLM emits the quote with a
        # space where the newline was. Should still match.
        transcript = "[00:05] 첫번째 줄\n[00:08] 두번째 줄"
        openai = _make_openai_mock(response=_mock_openai_response(
            products=[{
                "llm_label": "x",
                "spoken_aliases": ["x"],
                "first_mention_ms": 5000,
                "example_quote": "첫번째 줄  두번째 줄",  # collapsed ws
                "confidence": 0.8,
            }],
        ))
        enumerator = TranscriptEnumerator(openai_client=openai)
        result = await enumerator.enumerate(transcript=transcript)
        assert len(result.products) == 1
        assert result.dropped_count == 0


# ======================================================================
# service helpers
# ======================================================================


class TestNormalizeTerm:
    def test_lowercases_latin(self):
        assert _normalize_term("Dalsim") == "dalsim"

    def test_strips_whitespace(self):
        assert _normalize_term("  brand  ") == "brand"

    def test_korean_unchanged(self):
        # Korean has no case; casefold is a no-op.
        assert _normalize_term("달심") == "달심"


class TestBuildDedupTermSet:
    def test_includes_label_and_aliases(self):
        e1 = MagicMock()
        e1.llm_label = "Dalsim"
        e1.spoken_aliases = ["달심", "Dal"]
        e2 = MagicMock()
        e2.llm_label = "닥터포헤어"
        e2.spoken_aliases = []
        terms = _build_dedup_term_set([e1, e2])
        assert terms == {"dalsim", "달심", "dal", "닥터포헤어"}

    def test_skips_empty_labels(self):
        e = MagicMock()
        e.llm_label = ""
        e.spoken_aliases = ["", None]  # None should not blow up
        # Filter ``None`` through the alias handling.
        e.spoken_aliases = ["", "valid"]
        terms = _build_dedup_term_set([e])
        assert terms == {"valid"}


class TestHasTermOverlap:
    def test_label_match_blocks(self):
        existing = {"dalsim"}
        product = SimpleNamespace(llm_label="Dalsim", spoken_aliases=[])
        assert _has_term_overlap(product, existing) is True

    def test_alias_match_blocks(self):
        existing = {"달심"}
        product = SimpleNamespace(
            llm_label="Some New Brand",
            spoken_aliases=["달심", "기타"],
        )
        assert _has_term_overlap(product, existing) is True

    def test_no_overlap_passes(self):
        existing = {"dalsim", "닥터포헤어"}
        product = SimpleNamespace(
            llm_label="제주도 패키지",
            spoken_aliases=["제주", "5박6일"],
        )
        assert _has_term_overlap(product, existing) is False


class TestToCatalogRow:
    def test_sets_stt_provenance(self):
        product = SimpleNamespace(
            llm_label="제주도 5박6일",
            spoken_aliases=["제주", "5박6일"],
            first_mention_ms=245_000,
            example_quote="제주도 5박6일 패키지",
            confidence=0.92,
        )
        org = uuid4()
        video = uuid4()
        row = _to_catalog_row(
            product=product,
            org_id=org,
            video_id=video,
            prompt_version="v1.0",
        )
        assert row["enumeration_source"] == "stt"
        assert row["enumeration_version"] == STT_ENUMERATION_VERSION
        assert row["enumeration_prompt_version"] == "v1.0"
        assert row["llm_label"] == "제주도 5박6일"
        assert row["first_mention_ms"] == 245_000
        assert row["example_quote"] == "제주도 5박6일 패키지"
        assert row["enumeration_confidence"] == pytest.approx(0.92)

    def test_vision_only_fields_null(self):
        product = SimpleNamespace(
            llm_label="x",
            spoken_aliases=["x"],
            first_mention_ms=0,
            example_quote="x",
            confidence=0.5,
        )
        row = _to_catalog_row(
            product=product,
            org_id=uuid4(),
            video_id=uuid4(),
            prompt_version="v1.0",
        )
        for field in (
            "canonical_crop_s3_key",
            "canonical_video_id",
            "canonical_frame_idx",
            "canonical_bbox_x",
            "canonical_bbox_y",
            "canonical_bbox_w",
            "canonical_bbox_h",
            "siglip2_embedding",
            "prominence_score",
        ):
            assert row[field] is None, (
                f"{field} must be NULL on STT-source row"
            )

    def test_aliases_marked_already_generated(self):
        # STT entries skip the alias-generation second hop because
        # the LLM already saw the spoken form. Marking
        # aliases_generated_at + aliases_prompt_version keeps the
        # backfill CLI's selection query from picking these up.
        product = SimpleNamespace(
            llm_label="x",
            spoken_aliases=["a", "b"],
            first_mention_ms=0,
            example_quote="x",
            confidence=0.5,
        )
        row = _to_catalog_row(
            product=product,
            org_id=uuid4(),
            video_id=uuid4(),
            prompt_version="v1.0",
        )
        assert row["spoken_aliases"] == ["a", "b"]
        assert row["aliases_generated_at"] is not None
        assert row["aliases_prompt_version"] == "v1.0"


# ======================================================================
# service.run_stt_enumeration (orchestrator)
# ======================================================================


def _make_session_with_repo(*, existing_entries: list[MagicMock]):
    """Build a mock session whose ``ProductCatalogRepository`` returns
    the given existing entries on ``list_active_by_video`` and
    captures ``bulk_insert`` calls for assertion.
    """
    session = MagicMock()
    session.execute = AsyncMock()
    return session


@pytest.fixture
def patch_repo(monkeypatch):
    """Patch the ProductCatalogRepository where service.py uses it.

    Pattern B: patch BOTH the package-level export AND the module-
    bound name. service.py imports ``ProductCatalogRepository`` at
    module load, so patching the source isn't enough — we patch
    the bound name on the module too.
    """
    repo_factory = MagicMock()
    monkeypatch.setattr(
        "app.modules.shorts_auto_product.enumerate_stt.service.ProductCatalogRepository",
        repo_factory,
    )
    return repo_factory


class TestRunSttEnumeration:
    @pytest.mark.asyncio
    async def test_transcript_unavailable_returns_zero(self, patch_repo):
        os_client = _make_os_mock(hits=[])  # zero scenes
        openai = MagicMock()
        session = MagicMock()
        result = await run_stt_enumeration(
            session=session,
            os_client=os_client,
            openai_client=openai,
            org_id=uuid4(),
            video_db_id=uuid4(),
            video_drive_id="gd_silent",
        )
        assert result == 0
        # Repository never instantiated — early return path
        patch_repo.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_failure_returns_zero(self, patch_repo):
        os_client = _make_os_mock(hits=[
            _hit(scene_id="s1", start_ms=0, transcript_raw="발화 있음"),
        ])
        openai = MagicMock()
        openai.chat = MagicMock()
        openai.chat.completions = MagicMock()
        openai.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("openai down"),
        )
        session = MagicMock()
        result = await run_stt_enumeration(
            session=session,
            os_client=os_client,
            openai_client=openai,
            org_id=uuid4(),
            video_db_id=uuid4(),
            video_drive_id="gd_test",
        )
        assert result == 0
        patch_repo.assert_not_called()

    @pytest.mark.asyncio
    async def test_zero_products_returns_zero(self, patch_repo):
        os_client = _make_os_mock(hits=[
            _hit(scene_id="s1", start_ms=0, transcript_raw="발화"),
        ])
        openai = _make_openai_mock(response=_mock_openai_response(
            products=[],  # LLM correctly emitted nothing
        ))
        session = MagicMock()
        result = await run_stt_enumeration(
            session=session,
            os_client=os_client,
            openai_client=openai,
            org_id=uuid4(),
            video_db_id=uuid4(),
            video_drive_id="gd_test",
        )
        assert result == 0
        # Did not get to the dedup-and-insert phase
        patch_repo.assert_not_called()

    @pytest.mark.asyncio
    async def test_happy_path_inserts_after_dedup(self, patch_repo):
        os_client = _make_os_mock(hits=[
            _hit(scene_id="s1", start_ms=5_000,
                 transcript_raw="달심 주스를 소개합니다"),
            _hit(scene_id="s2", start_ms=10_000,
                 transcript_raw="제주도 5박6일 패키지"),
        ])
        openai = _make_openai_mock(response=_mock_openai_response(
            products=[
                {
                    "llm_label": "달심 주스",
                    "spoken_aliases": ["달심"],
                    "first_mention_ms": 5_000,
                    "example_quote": "달심 주스를 소개합니다",
                    "confidence": 0.9,
                },
                {
                    "llm_label": "제주도 패키지",
                    "spoken_aliases": ["제주"],
                    "first_mention_ms": 10_000,
                    "example_quote": "제주도 5박6일 패키지",
                    "confidence": 0.85,
                },
            ],
        ))
        # Existing vision row for 달심 — STT product should dedupe out.
        existing_entry = MagicMock()
        existing_entry.llm_label = "Dalsim 주스"
        existing_entry.spoken_aliases = ["달심"]
        repo = MagicMock()
        repo.list_active_by_video = AsyncMock(return_value=[existing_entry])
        repo.bulk_insert = AsyncMock(side_effect=lambda entries: [
            MagicMock() for _ in entries
        ])
        patch_repo.return_value = repo

        session = MagicMock()
        result = await run_stt_enumeration(
            session=session,
            os_client=os_client,
            openai_client=openai,
            org_id=uuid4(),
            video_db_id=uuid4(),
            video_drive_id="gd_test",
        )
        # 1 deduped (달심), 1 survived (제주도)
        assert result == 1
        repo.bulk_insert.assert_awaited_once()
        inserted_rows = repo.bulk_insert.await_args.kwargs["entries"]
        assert len(inserted_rows) == 1
        assert inserted_rows[0]["llm_label"] == "제주도 패키지"
        assert inserted_rows[0]["enumeration_source"] == "stt"

    @pytest.mark.asyncio
    async def test_all_deduped_returns_zero_and_skips_insert(self, patch_repo):
        os_client = _make_os_mock(hits=[
            _hit(scene_id="s1", start_ms=0, transcript_raw="달심"),
        ])
        openai = _make_openai_mock(response=_mock_openai_response(
            products=[{
                "llm_label": "달심",
                "spoken_aliases": ["달심"],
                "first_mention_ms": 0,
                "example_quote": "달심",
                "confidence": 0.9,
            }],
        ))
        existing = MagicMock()
        existing.llm_label = "Dalsim"
        existing.spoken_aliases = ["달심"]
        repo = MagicMock()
        repo.list_active_by_video = AsyncMock(return_value=[existing])
        repo.bulk_insert = AsyncMock()
        patch_repo.return_value = repo

        result = await run_stt_enumeration(
            session=MagicMock(),
            os_client=os_client,
            openai_client=openai,
            org_id=uuid4(),
            video_db_id=uuid4(),
            video_drive_id="gd_test",
        )
        assert result == 0
        repo.bulk_insert.assert_not_called()


# ======================================================================
# error class hierarchy
# ======================================================================


def test_error_hierarchy():
    """STTEnumerationError is the base; both specializations subclass it.
    """
    assert issubclass(TranscriptUnavailableError, STTEnumerationError)
    assert issubclass(EnumerationLLMError, STTEnumerationError)
    assert issubclass(STTEnumerationError, Exception)
