"""Factory + rollout-pct hash tests.

The factory is the ONLY place that decides pure-vs-LLM routing. These
tests pin the boundary so a future change can't accidentally invert the
default behavior (should always default OFF when flag is unset).
"""

from __future__ import annotations

from types import SimpleNamespace
from uuid import UUID, uuid4

from app.modules.shorts_auto.scorers import (
    PureSceneScorer,
    build_scorer,
    should_use_llm_for_request,
)
from app.modules.shorts_auto.scorers.factory import _hash_bucket


def _settings(**overrides):
    base = {
        "auto_shorts_llm_enabled": False,
        "auto_shorts_llm_rollout_pct": 0,
        "auto_shorts_llm_model": "gpt-4o-mini",
        "auto_shorts_llm_daily_budget_usd": 25.0,
        "auto_shorts_llm_timeout_sec": 8.0,
        "auto_shorts_llm_max_scenes": 50,
        "auto_shorts_llm_estimated_cost_per_call_usd": 0.003,
        "auto_shorts_llm_prompt_version": "test-v1",
        "openai_api_key": "sk-test",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


class TestShouldUseLlm:
    def test_off_when_flag_disabled(self):
        assert not should_use_llm_for_request(
            _settings(auto_shorts_llm_enabled=False, auto_shorts_llm_rollout_pct=100),
            org_id=uuid4(),
            video_id="v",
        )

    def test_off_when_rollout_zero(self):
        assert not should_use_llm_for_request(
            _settings(auto_shorts_llm_enabled=True, auto_shorts_llm_rollout_pct=0),
            org_id=uuid4(),
            video_id="v",
        )

    def test_on_when_rollout_100(self):
        # 100% rollout short-circuits the hash bucket check.
        assert should_use_llm_for_request(
            _settings(auto_shorts_llm_enabled=True, auto_shorts_llm_rollout_pct=100),
            org_id=uuid4(),
            video_id="v",
        )

    def test_partial_rollout_is_deterministic(self):
        s = _settings(auto_shorts_llm_enabled=True, auto_shorts_llm_rollout_pct=50)
        org = UUID("00000000-0000-0000-0000-000000000001")
        a = should_use_llm_for_request(s, org_id=org, video_id="vid-x")
        b = should_use_llm_for_request(s, org_id=org, video_id="vid-x")
        assert a == b  # same input → same decision

    def test_hash_bucket_is_stable_and_bounded(self):
        assert 0 <= _hash_bucket("foo") < 100
        assert _hash_bucket("foo") == _hash_bucket("foo")


class TestBuildScorer:
    def test_default_returns_pure(self):
        scorer = build_scorer(_settings())
        assert isinstance(scorer, PureSceneScorer)
        assert scorer.name == "pure"

    def test_use_llm_false_returns_pure(self):
        scorer = build_scorer(_settings(auto_shorts_llm_enabled=True), use_llm=False)
        assert scorer.name == "pure"

    def test_use_llm_true_returns_llm_scorer(self):
        scorer = build_scorer(
            _settings(auto_shorts_llm_enabled=True), use_llm=True
        )
        assert scorer.name == "llm"
