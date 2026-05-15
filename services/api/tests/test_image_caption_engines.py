"""Unit tests for the image caption engines package.

Covers the engine subsystem under app.modules.image_caption.engines:
  - base:            Protocol conformance, dataclass identity
  - openai_prompt:   schema shape, locked enums, banned terms presence
  - post_validation: table-driven person-safety checks (Korean + English)
  - openai_client:   budget tracker, error classifier, retry loop
                     (with mocked OpenAI SDK surface), usage extraction,
                     cost estimator
  - openai_engine:   happy path, parse failure, person-safety violation,
                     prompt cache stability, image sniffing
  - factory:         engine construction, missing key raises

Tests do NOT hit the real OpenAI API. Integration tests with a live key
live under tests/integration/ (separate CI lane, gated by env).
"""

from __future__ import annotations

import base64
import json
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest

from app.modules.image_caption.engines.base import (
    BudgetExceededError,
    CaptionEngine,
    CaptionResult,
    PersonSafetyViolation,
    RetryableEngineError,
    TerminalEngineError,
    TokenUsage,
)
from app.modules.image_caption.engines.openai_client import (
    InMemoryBudgetTracker,
    MODEL_PRICING_USD_PER_MTOK,
    OpenAICallResult,
    OpenAICaptionClient,
    _classify_error,
    _estimate_cost_usd,
    _extract_usage,
)
from app.modules.image_caption.engines.openai_engine import (
    OpenAICaptionEngine,
    _parse_structured,
    _sniff_mime,
    _to_data_url,
)
from app.modules.image_caption.engines.openai_prompt import (
    BANNED_PERSON_TERMS,
    FEW_SHOT_TURNS,
    JSON_SCHEMA,
    PRODUCT_CATEGORIES,
    PROMPT_VERSION,
    SEASONS,
    SYSTEM_PROMPT,
)
from app.modules.image_caption.engines.post_validation import (
    assert_person_safety,
    find_banned_terms,
)


# ─── base ────────────────────────────────────────────────────────────────────


class TestProtocolConformance:
    def test_fake_engine_satisfies_protocol(self):
        class FakeEngine:
            name = "fake"

            def caption(self, image_path, hints=None):
                return CaptionResult(
                    caption="hi", prompt_version="t", model="fake"
                )

            def close(self):
                pass

        assert isinstance(FakeEngine(), CaptionEngine)

    def test_missing_method_fails_protocol(self):
        class Broken:
            name = "broken"

        assert not isinstance(Broken(), CaptionEngine)


class TestCaptionResultDataclass:
    def test_default_usage(self):
        r = CaptionResult(caption="x", prompt_version="v", model="m")
        assert r.usage == TokenUsage()
        assert r.structured is None
        assert r.validation_failure is None

    def test_frozen(self):
        r = CaptionResult(caption="x", prompt_version="v", model="m")
        with pytest.raises(Exception):
            r.caption = "y"  # type: ignore[misc]


# ─── openai_prompt ───────────────────────────────────────────────────────────


class TestPromptAssets:
    def test_prompt_version_not_empty(self):
        assert PROMPT_VERSION
        assert isinstance(PROMPT_VERSION, str)

    def test_product_categories_locked_exact_10(self):
        # LOCKED per phase 1. Changing this list is an explicit decision
        # that requires re-backfill.
        expected = [
            "스킨케어", "색조화장품", "건강기능식품", "음료", "식품",
            "패션", "전자제품", "생활용품", "여행/레저", "기타",
        ]
        assert PRODUCT_CATEGORIES == expected

    def test_seasons_locked(self):
        assert SEASONS == ["봄", "여름", "가을", "겨울", "시즌무관"]

    def test_schema_has_all_required_fields(self):
        schema = JSON_SCHEMA["schema"]
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == {
            "caption", "brand", "brand_en", "product_category",
            "background_color_ko", "dominant_colors_ko",
            "mood", "props", "season", "has_person",
        }

    def test_schema_strict_mode(self):
        assert JSON_SCHEMA["strict"] is True

    def test_schema_enums_wired_to_constants(self):
        props = JSON_SCHEMA["schema"]["properties"]
        assert props["product_category"]["enum"] == PRODUCT_CATEGORIES
        assert props["season"]["enum"] == SEASONS

    def test_schema_array_bounds(self):
        props = JSON_SCHEMA["schema"]["properties"]
        assert props["dominant_colors_ko"]["minItems"] == 2
        assert props["dominant_colors_ko"]["maxItems"] == 4
        assert props["mood"]["minItems"] == 2
        assert props["mood"]["maxItems"] == 4

    def test_banned_terms_non_empty(self):
        assert len(BANNED_PERSON_TERMS) >= 20
        assert "쇼호스트" in BANNED_PERSON_TERMS
        assert "모델" in BANNED_PERSON_TERMS
        assert "얼굴" in BANNED_PERSON_TERMS

    def test_few_shot_turns_are_user_assistant_pairs(self):
        assert len(FEW_SHOT_TURNS) % 2 == 0
        for i in range(0, len(FEW_SHOT_TURNS), 2):
            assert FEW_SHOT_TURNS[i]["role"] == "user"
            assert FEW_SHOT_TURNS[i + 1]["role"] == "assistant"

    def test_few_shot_assistant_turns_are_valid_json(self):
        for i in range(1, len(FEW_SHOT_TURNS), 2):
            parsed = json.loads(FEW_SHOT_TURNS[i]["content"])
            assert "caption" in parsed
            assert parsed["product_category"] in PRODUCT_CATEGORIES
            assert parsed["season"] in SEASONS
            assert isinstance(parsed["has_person"], bool)

    def test_few_shot_captions_are_person_safe(self):
        for i in range(1, len(FEW_SHOT_TURNS), 2):
            parsed = json.loads(FEW_SHOT_TURNS[i]["content"])
            assert_person_safety(
                parsed["caption"], parsed["has_person"], BANNED_PERSON_TERMS
            )

    def test_system_prompt_forbids_person_description(self):
        assert "인물" in SYSTEM_PROMPT
        assert "금지" in SYSTEM_PROMPT


# ─── post_validation ─────────────────────────────────────────────────────────


PERSON_SAFETY_CASES = [
    # (caption, has_person, should_raise)
    ("민트 배경에 스킨케어 제품이 진열되어 있다", False, False),
    ("민트 배경에 스킨케어 제품이 진열되어 있다", True, False),
    ("쇼호스트가 제품을 들고 있다", True, True),
    ("쇼호스트가 제품을 들고 있다", False, True),
    ("모델이 입은 원피스", False, True),
    ("쇼호스트님이 설명하는 장면", True, True),
    ("A woman holds the product", True, True),
    ("Handmade ceramic bowl", False, False),
    ("A person smiles at the camera", True, True),
    ("연한 핑크 배경에 향수병", False, False),
    ("표정이 환한 장면", False, True),
    ("", False, False),
    ("캐릭터가 그려진 일러스트", False, False),
]


@pytest.mark.parametrize("caption,has_person,should_raise", PERSON_SAFETY_CASES)
def test_person_safety(caption, has_person, should_raise):
    if should_raise:
        with pytest.raises(PersonSafetyViolation):
            assert_person_safety(caption, has_person, BANNED_PERSON_TERMS)
    else:
        assert_person_safety(caption, has_person, BANNED_PERSON_TERMS)


class TestFindBannedTerms:
    def test_empty_caption(self):
        assert find_banned_terms("", BANNED_PERSON_TERMS) == []

    def test_no_hits(self):
        assert find_banned_terms("튤립과 유리 구슬", BANNED_PERSON_TERMS) == []

    def test_korean_substring_match(self):
        hits = find_banned_terms("쇼호스트가 서 있다", BANNED_PERSON_TERMS)
        assert "쇼호스트" in hits

    def test_english_word_boundary(self):
        # "hand" is banned in English (body part, implies person).
        # "handmade" must NOT match because the regex is word-boundary aware.
        assert find_banned_terms("handmade bowl", BANNED_PERSON_TERMS) == []
        hits = find_banned_terms("a hand holds the cup", BANNED_PERSON_TERMS)
        assert "hand" in hits

    def test_case_insensitive(self):
        hits = find_banned_terms("A MODEL on stage", BANNED_PERSON_TERMS)
        assert "model" in hits

    def test_dedup(self):
        hits = find_banned_terms("model and model and model", BANNED_PERSON_TERMS)
        assert hits.count("model") == 1


# ─── budget tracker ──────────────────────────────────────────────────────────


class TestInMemoryBudgetTracker:
    def test_allows_under_budget(self):
        t = InMemoryBudgetTracker(daily_budget_usd=1.0)
        t.check_and_reserve(0.1)
        t.record(0.1)
        assert t.spent_today_usd() == pytest.approx(0.1, rel=1e-6)

    def test_blocks_over_budget(self):
        t = InMemoryBudgetTracker(daily_budget_usd=1.0)
        t.check_and_reserve(0.6)
        t.record(0.6)
        with pytest.raises(BudgetExceededError):
            t.check_and_reserve(0.5)

    def test_reservation_prevents_overshoot_under_concurrency(self):
        t = InMemoryBudgetTracker(daily_budget_usd=1.0)
        t.check_and_reserve(0.6)
        with pytest.raises(BudgetExceededError):
            t.check_and_reserve(0.5)

    def test_record_releases_reservation(self):
        t = InMemoryBudgetTracker(daily_budget_usd=1.0)
        t.check_and_reserve(0.6)
        t.record(0.6)
        t.check_and_reserve(0.3)
        t.record(0.3)
        assert t.spent_today_usd() == pytest.approx(0.9, rel=1e-6)

    def test_thread_safety(self):
        t = InMemoryBudgetTracker(daily_budget_usd=100.0)
        errors: list[Exception] = []

        def worker():
            try:
                for _ in range(50):
                    t.check_and_reserve(0.01)
                    t.record(0.01)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()

        assert errors == []
        assert t.spent_today_usd() == pytest.approx(8 * 50 * 0.01, rel=1e-3)

    def test_day_rollover(self, monkeypatch):
        from app.modules.image_caption.engines import openai_client as client_mod

        t = InMemoryBudgetTracker(daily_budget_usd=1.0)
        t.check_and_reserve(0.9)
        t.record(0.9)

        original = client_mod._today_utc
        days = {"offset": 0}

        def fake_today() -> str:
            import datetime as dt

            return (
                dt.datetime.now(dt.timezone.utc)
                + dt.timedelta(days=days["offset"])
            ).strftime("%Y-%m-%d")

        monkeypatch.setattr(client_mod, "_today_utc", fake_today)

        days["offset"] = 1
        t.check_and_reserve(0.9)
        t.record(0.9)
        assert t.spent_today_usd() == pytest.approx(0.9, rel=1e-6)

        monkeypatch.setattr(client_mod, "_today_utc", original)


# ─── cost estimator ──────────────────────────────────────────────────────────


class TestCostEstimator:
    def test_gpt_4o_cost_matches_table(self):
        usage = TokenUsage(
            prompt_tokens=2000,
            completion_tokens=300,
            total_tokens=2300,
            cached_prompt_tokens=0,
        )
        cost = _estimate_cost_usd("gpt-4o", usage)
        expected = 2000 * 2.50 / 1_000_000 + 300 * 10.00 / 1_000_000
        assert cost == pytest.approx(expected, rel=1e-6)

    def test_cached_tokens_reduce_cost(self):
        uncached = TokenUsage(
            prompt_tokens=2000, completion_tokens=300, total_tokens=2300
        )
        cached = TokenUsage(
            prompt_tokens=2000,
            completion_tokens=300,
            total_tokens=2300,
            cached_prompt_tokens=1800,
        )
        assert _estimate_cost_usd("gpt-4o", cached) < _estimate_cost_usd(
            "gpt-4o", uncached
        )

    def test_unknown_model_falls_back_to_gpt_4o(self):
        usage = TokenUsage(prompt_tokens=100, completion_tokens=10, total_tokens=110)
        unknown = _estimate_cost_usd("gpt-future-2099", usage)
        known = _estimate_cost_usd("gpt-4o", usage)
        assert unknown == pytest.approx(known, rel=1e-6)

    def test_pricing_table_has_gpt_4o(self):
        assert "gpt-4o" in MODEL_PRICING_USD_PER_MTOK


# ─── usage extractor ─────────────────────────────────────────────────────────


class TestExtractUsage:
    def test_attr_style_response(self):
        usage_obj = SimpleNamespace(
            prompt_tokens=1000,
            completion_tokens=200,
            total_tokens=1200,
            prompt_tokens_details=SimpleNamespace(cached_tokens=500),
        )
        response = SimpleNamespace(usage=usage_obj)
        u = _extract_usage(response)
        assert u.prompt_tokens == 1000
        assert u.completion_tokens == 200
        assert u.total_tokens == 1200
        assert u.cached_prompt_tokens == 500

    def test_no_usage_returns_zeros(self):
        response = SimpleNamespace(usage=None)
        u = _extract_usage(response)
        assert u == TokenUsage()

    def test_total_derived_when_missing(self):
        usage_obj = SimpleNamespace(
            prompt_tokens=100,
            completion_tokens=20,
            total_tokens=0,
            prompt_tokens_details=None,
        )
        response = SimpleNamespace(usage=usage_obj)
        u = _extract_usage(response)
        assert u.total_tokens == 120


# ─── error classifier ───────────────────────────────────────────────────────


class _FakeStatusErr(Exception):
    def __init__(self, status_code: int) -> None:
        super().__init__(f"status {status_code}")
        self.status_code = status_code


class TestErrorClassifier:
    def test_429_retryable(self):
        assert _classify_error(_FakeStatusErr(429)) == "retryable"

    def test_500_retryable(self):
        assert _classify_error(_FakeStatusErr(503)) == "retryable"

    def test_400_terminal(self):
        assert _classify_error(_FakeStatusErr(400)) == "terminal"

    def test_401_terminal(self):
        assert _classify_error(_FakeStatusErr(401)) == "terminal"

    def test_unknown_defaults_retryable(self):
        assert _classify_error(RuntimeError("network ???")) == "retryable"


# ─── openai_client retry loop with mocked SDK ───────────────────────────────


@pytest.fixture()
def fake_openai(monkeypatch):
    """Provide a fake `openai` module and fake OpenAI() client class."""

    fake_module = SimpleNamespace()
    fake_module.RateLimitError = type("RateLimitError", (Exception,), {})
    fake_module.APIConnectionError = type("APIConnectionError", (Exception,), {})
    fake_module.APITimeoutError = type("APITimeoutError", (Exception,), {})
    fake_module.InternalServerError = type("InternalServerError", (Exception,), {})
    fake_module.BadRequestError = type("BadRequestError", (Exception,), {})
    fake_module.AuthenticationError = type("AuthenticationError", (Exception,), {})
    fake_module.PermissionDeniedError = type("PermissionDeniedError", (Exception,), {})
    fake_module.NotFoundError = type("NotFoundError", (Exception,), {})
    fake_module.UnprocessableEntityError = type("UnprocessableEntityError", (Exception,), {})

    class FakeChatCompletions:
        def __init__(self):
            self.calls: list[dict[str, Any]] = []
            self.responses: list[Any] = []

        def queue(self, *items):
            self.responses.extend(items)

        def create(self, **kwargs):
            self.calls.append(kwargs)
            if not self.responses:
                raise RuntimeError("no canned responses remaining")
            item = self.responses.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

    class FakeChat:
        def __init__(self, completions):
            self.completions = completions

    class FakeOpenAI:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            self.completions = FakeChatCompletions()
            self.chat = FakeChat(self.completions)

    fake_module.OpenAI = FakeOpenAI

    monkeypatch.setitem(sys.modules, "openai", fake_module)
    return fake_module


def _make_response(content: str, prompt_tokens=2000, completion_tokens=300, cached=0):
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content),
                finish_reason="stop",
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            prompt_tokens_details=SimpleNamespace(cached_tokens=cached),
        ),
    )


def _make_client(fake_openai, *, daily_budget=10.0, max_retries=3):
    tracker = InMemoryBudgetTracker(daily_budget_usd=daily_budget)
    return OpenAICaptionClient(
        api_key="sk-fake",
        model="gpt-4o",
        timeout_s=5.0,
        max_concurrency=2,
        budget_tracker=tracker,
        max_retries=max_retries,
        backoff_base_s=0.0,
        backoff_max_s=0.0,
    )


class TestOpenAIClientCall:
    def test_success_first_try(self, fake_openai, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda s: None)
        client = _make_client(fake_openai)
        fake_client = client._client  # type: ignore[attr-defined]
        fake_client.completions.queue(
            _make_response('{"caption":"ok","has_person":false}')
        )

        result = client.call(
            messages=[{"role": "system", "content": "x"}],
            response_format={"name": "t", "strict": True, "schema": {}},
        )
        assert isinstance(result, OpenAICallResult)
        assert result.text == '{"caption":"ok","has_person":false}'
        assert result.usage.prompt_tokens == 2000
        assert result.cost_usd > 0
        assert len(fake_client.completions.calls) == 1

    def test_retry_then_success(self, fake_openai, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda s: None)
        client = _make_client(fake_openai)
        fake_client = client._client  # type: ignore[attr-defined]
        fake_client.completions.queue(
            fake_openai.RateLimitError("rate limited"),
            fake_openai.InternalServerError("5xx"),
            _make_response('{"caption":"ok","has_person":false}'),
        )

        result = client.call(
            messages=[{"role": "system", "content": "x"}],
            response_format={"name": "t", "strict": True, "schema": {}},
        )
        assert result.text.startswith("{")
        assert len(fake_client.completions.calls) == 3

    def test_retry_exhaustion_raises_retryable(self, fake_openai, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda s: None)
        client = _make_client(fake_openai, max_retries=2)
        fake_client = client._client  # type: ignore[attr-defined]
        fake_client.completions.queue(
            fake_openai.RateLimitError("r"),
            fake_openai.RateLimitError("r"),
            fake_openai.RateLimitError("r"),
        )

        with pytest.raises(RetryableEngineError):
            client.call(
                messages=[{"role": "system", "content": "x"}],
                response_format={"name": "t", "strict": True, "schema": {}},
            )

    def test_terminal_error_no_retry(self, fake_openai, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda s: None)
        client = _make_client(fake_openai)
        fake_client = client._client  # type: ignore[attr-defined]
        fake_client.completions.queue(
            fake_openai.BadRequestError("bad"),
        )

        with pytest.raises(TerminalEngineError):
            client.call(
                messages=[{"role": "system", "content": "x"}],
                response_format={"name": "t", "strict": True, "schema": {}},
            )
        assert len(fake_client.completions.calls) == 1

    def test_budget_blocks_before_call(self, fake_openai, monkeypatch):
        monkeypatch.setattr(time, "sleep", lambda s: None)
        tracker = InMemoryBudgetTracker(daily_budget_usd=0.001)
        client = OpenAICaptionClient(
            api_key="sk-fake",
            model="gpt-4o",
            timeout_s=5.0,
            max_concurrency=2,
            budget_tracker=tracker,
            max_retries=0,
            backoff_base_s=0.0,
            backoff_max_s=0.0,
            estimated_cost_per_call_usd=0.012,
        )
        fake_client = client._client  # type: ignore[attr-defined]
        fake_client.completions.queue(
            _make_response('{"caption":"ok","has_person":false}')
        )

        with pytest.raises(BudgetExceededError):
            client.call(
                messages=[{"role": "system", "content": "x"}],
                response_format={"name": "t", "strict": True, "schema": {}},
            )

        assert len(fake_client.completions.calls) == 0


# ─── openai_engine (integration of prompt + client) ─────────────────────────


@pytest.fixture()
def tiny_png(tmp_path) -> Path:
    png_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAusB9G6"
        "OAp0AAAAASUVORK5CYII="
    )
    p = tmp_path / "tiny.png"
    p.write_bytes(png_bytes)
    return p


class _StubClient:
    """Stand-in for OpenAICaptionClient. Captures invocations."""

    def __init__(self, response_text: str, *, latency_ms: int = 42):
        self.response_text = response_text
        self.latency_ms = latency_ms
        self.calls: list[dict[str, Any]] = []
        self.model = "gpt-4o"

    def call(self, *, messages, response_format, seed=42):
        self.calls.append({"messages": messages, "response_format": response_format})
        return OpenAICallResult(
            text=self.response_text,
            usage=TokenUsage(
                prompt_tokens=2000,
                completion_tokens=300,
                total_tokens=2300,
                cached_prompt_tokens=1500,
            ),
            model="gpt-4o",
            cost_usd=0.008,
            latency_ms=self.latency_ms,
        )

    def close(self):
        pass


class TestOpenAIEngineHappyPath:
    def test_returns_caption_and_structured(self, tiny_png):
        payload = {
            "caption": "민트 배경에 스킨케어 제품이 진열되어 있다",
            "brand": "브링그린",
            "brand_en": "BRINGGREEN",
            "product_category": "스킨케어",
            "background_color_ko": "민트",
            "dominant_colors_ko": ["민트", "화이트"],
            "mood": ["내추럴", "싱그러움"],
            "props": ["잎사귀"],
            "season": "시즌무관",
            "has_person": False,
        }
        stub = _StubClient(json.dumps(payload, ensure_ascii=False))
        engine = OpenAICaptionEngine(client=stub)  # type: ignore[arg-type]

        result = engine.caption(tiny_png, hints={"file_name": "test.jpg"})
        assert result.caption == payload["caption"]
        assert result.structured == payload
        assert result.validation_failure is None
        assert result.prompt_version == PROMPT_VERSION
        assert result.model == "gpt-4o"
        assert result.latency_ms == 42
        assert result.usage.cached_prompt_tokens == 1500

    def test_prompt_layout_stable_across_calls(self, tiny_png):
        stub = _StubClient(json.dumps({
            "caption": "a", "brand": None, "brand_en": None,
            "product_category": "기타", "background_color_ko": "",
            "dominant_colors_ko": ["a", "b"], "mood": ["a", "b"],
            "props": [], "season": "시즌무관", "has_person": False,
        }, ensure_ascii=False))
        engine = OpenAICaptionEngine(client=stub)  # type: ignore[arg-type]

        engine.caption(tiny_png)
        engine.caption(tiny_png)

        msgs_a = stub.calls[0]["messages"]
        msgs_b = stub.calls[1]["messages"]
        assert msgs_a[:-1] == msgs_b[:-1]
        assert msgs_a[0]["role"] == "system"
        assert msgs_a[0]["content"] == SYSTEM_PROMPT
        last = msgs_a[-1]
        assert last["role"] == "user"
        assert any(c.get("type") == "image_url" for c in last["content"])

    def test_hints_appear_in_user_turn(self, tiny_png):
        stub = _StubClient(json.dumps({
            "caption": "a", "brand": None, "brand_en": None,
            "product_category": "기타", "background_color_ko": "",
            "dominant_colors_ko": ["a", "b"], "mood": ["a", "b"],
            "props": [], "season": "시즌무관", "has_person": False,
        }, ensure_ascii=False))
        engine = OpenAICaptionEngine(client=stub)  # type: ignore[arg-type]
        engine.caption(tiny_png, hints={"file_name": "brand_shot.jpg", "library_name": "dev"})

        user_msg = stub.calls[0]["messages"][-1]
        text_part = next(c for c in user_msg["content"] if c["type"] == "text")
        assert "brand_shot.jpg" in text_part["text"]
        assert "dev" in text_part["text"]


class TestOpenAIEngineFailureModes:
    def test_parse_error_returns_empty_caption_with_failure_code(self, tiny_png):
        stub = _StubClient("not valid json")
        engine = OpenAICaptionEngine(client=stub)  # type: ignore[arg-type]
        result = engine.caption(tiny_png)
        assert result.caption == ""
        assert result.validation_failure is not None
        assert result.validation_failure.startswith("parse_error:")

    def test_missing_caption_field_returns_failure(self, tiny_png):
        stub = _StubClient(json.dumps({"brand": "x"}))
        engine = OpenAICaptionEngine(client=stub)  # type: ignore[arg-type]
        result = engine.caption(tiny_png)
        assert result.caption == ""
        assert result.validation_failure == "parse_error:missing_caption_field"

    def test_person_safety_violation_drops_caption(self, tiny_png):
        payload = {
            "caption": "쇼호스트가 제품을 소개한다",
            "brand": None, "brand_en": None,
            "product_category": "기타", "background_color_ko": "",
            "dominant_colors_ko": ["a", "b"], "mood": ["a", "b"],
            "props": [], "season": "시즌무관", "has_person": True,
        }
        stub = _StubClient(json.dumps(payload, ensure_ascii=False))
        engine = OpenAICaptionEngine(client=stub)  # type: ignore[arg-type]

        result = engine.caption(tiny_png)
        assert result.caption == ""
        assert result.validation_failure == "person_terms_leaked"
        assert result.structured is not None

    def test_missing_image_raises_terminal(self, tmp_path):
        stub = _StubClient('{"caption":"x"}')
        engine = OpenAICaptionEngine(client=stub)  # type: ignore[arg-type]
        with pytest.raises(TerminalEngineError):
            engine.caption(tmp_path / "nope.jpg")

    def test_empty_image_raises_terminal(self, tmp_path):
        p = tmp_path / "empty.jpg"
        p.write_bytes(b"")
        stub = _StubClient('{"caption":"x"}')
        engine = OpenAICaptionEngine(client=stub)  # type: ignore[arg-type]
        with pytest.raises(TerminalEngineError):
            engine.caption(p)


class TestMimeAndDataUrl:
    def test_sniff_jpeg(self, tmp_path):
        p = tmp_path / "a.jpg"
        p.write_bytes(b"x")
        assert _sniff_mime(p) == "image/jpeg"

    def test_sniff_png(self, tmp_path):
        p = tmp_path / "a.png"
        p.write_bytes(b"x")
        assert _sniff_mime(p) == "image/png"

    def test_sniff_unknown_falls_back_to_jpeg(self, tmp_path):
        p = tmp_path / "a.weirdext"
        p.write_bytes(b"x")
        assert _sniff_mime(p) == "image/jpeg"

    def test_data_url_roundtrip(self):
        url = _to_data_url(b"hello", "image/png")
        assert url.startswith("data:image/png;base64,")
        tail = url.split(",", 1)[1]
        assert base64.b64decode(tail) == b"hello"


class TestParseStructured:
    def test_valid_object(self):
        parsed, err = _parse_structured('{"caption":"hi"}')
        assert err is None
        assert parsed == {"caption": "hi"}

    def test_empty(self):
        parsed, err = _parse_structured("")
        assert err == "empty_response"

    def test_invalid_json(self):
        parsed, err = _parse_structured("not json")
        assert err is not None and err.startswith("json_decode:")

    def test_not_object(self):
        parsed, err = _parse_structured("[1,2,3]")
        assert err == "not_object"

    def test_missing_caption(self):
        parsed, err = _parse_structured('{"brand":"x"}')
        assert err == "missing_caption_field"


# ─── factory ─────────────────────────────────────────────────────────────────


class TestFactory:
    def test_factory_builds_openai_engine(self, fake_openai):
        from app.modules.image_caption.engines.factory import (
            build_image_caption_engine,
        )

        settings = SimpleNamespace(
            openai_api_key="sk-fake",
            image_caption_model="gpt-4o",
            image_caption_image_detail="low",
            image_caption_timeout_s=5.0,
            image_caption_max_concurrency=2,
            image_caption_daily_budget_usd=50.0,
            image_caption_estimated_cost_per_call_usd=0.012,
        )
        engine = build_image_caption_engine(settings)
        assert engine.name == "openai"
        assert isinstance(engine, CaptionEngine)

    def test_factory_missing_key_raises(self, fake_openai):
        from app.modules.image_caption.engines.factory import (
            build_image_caption_engine,
        )

        settings = SimpleNamespace(openai_api_key="")
        with pytest.raises(RuntimeError, match="openai_api_key"):
            build_image_caption_engine(settings)
