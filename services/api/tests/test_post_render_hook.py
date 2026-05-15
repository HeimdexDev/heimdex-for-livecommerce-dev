"""Routing logic for the post-render Whisper refinement hook."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.modules.shorts_render import post_render_hook


def _settings(*, enabled=True, rollout_pct=100):
    return SimpleNamespace(
        auto_shorts_product_v2_whisper_refine_enabled=enabled,
        auto_shorts_product_v2_whisper_rollout_pct=rollout_pct,
    )


def _captured_log_text(
    caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> str:
    captured = capsys.readouterr()
    return caplog.text + captured.out + captured.err


@pytest.fixture
def schedule_calls(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Spy on ``refinement_service.schedule_refinement``."""
    calls: list[tuple] = []

    def _spy(parent_job_id):
        calls.append(("schedule", parent_job_id))

    monkeypatch.setattr(
        post_render_hook.refinement_service,
        "schedule_refinement",
        _spy,
    )
    return calls


class TestFlagOff:
    def test_master_flag_off_skips_silently(
        self, monkeypatch: pytest.MonkeyPatch, schedule_calls: list[tuple]
    ) -> None:
        monkeypatch.setattr(
            post_render_hook,
            "get_settings",
            lambda: _settings(enabled=False, rollout_pct=100),
        )
        post_render_hook.schedule_refinement_if_eligible(
            parent_job_id=uuid4(), org_id=uuid4()
        )
        assert schedule_calls == []


class TestRollout:
    def test_zero_rollout_skips(
        self, monkeypatch: pytest.MonkeyPatch, schedule_calls: list[tuple]
    ) -> None:
        monkeypatch.setattr(
            post_render_hook,
            "get_settings",
            lambda: _settings(enabled=True, rollout_pct=0),
        )
        post_render_hook.schedule_refinement_if_eligible(
            parent_job_id=uuid4(), org_id=uuid4()
        )
        assert schedule_calls == []

    def test_full_rollout_schedules(
        self, monkeypatch: pytest.MonkeyPatch, schedule_calls: list[tuple]
    ) -> None:
        monkeypatch.setattr(
            post_render_hook,
            "get_settings",
            lambda: _settings(enabled=True, rollout_pct=100),
        )
        parent_id = uuid4()
        post_render_hook.schedule_refinement_if_eligible(
            parent_job_id=parent_id, org_id=uuid4()
        )
        assert len(schedule_calls) == 1
        assert schedule_calls[0] == ("schedule", parent_id)

    def test_rollout_deterministic_per_org(
        self, monkeypatch: pytest.MonkeyPatch, schedule_calls: list[tuple]
    ) -> None:
        """Same org_id at same rollout_pct → same decision every time."""
        monkeypatch.setattr(
            post_render_hook,
            "get_settings",
            lambda: _settings(enabled=True, rollout_pct=50),
        )
        org_id = uuid4()
        for _ in range(3):
            post_render_hook.schedule_refinement_if_eligible(
                parent_job_id=uuid4(), org_id=org_id
            )
        # Either all 3 calls scheduled, or none — never partial
        assert len(schedule_calls) in (0, 3)


class TestErrorContract:
    def test_settings_load_failure_logged_not_raised(
        self,
        monkeypatch: pytest.MonkeyPatch,
        schedule_calls: list[tuple],
        caplog: pytest.LogCaptureFixture,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        caplog.set_level(logging.ERROR)

        def _explode():
            raise RuntimeError("settings broken")

        monkeypatch.setattr(post_render_hook, "get_settings", _explode)

        # Must not raise into caller
        post_render_hook.schedule_refinement_if_eligible(
            parent_job_id=uuid4(), org_id=uuid4()
        )
        assert schedule_calls == []
        assert "whisper_refine_hook_failed" in _captured_log_text(caplog, capsys)

    def test_schedule_call_failure_logged_not_raised(
        self,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        caplog.set_level(logging.ERROR)
        monkeypatch.setattr(
            post_render_hook,
            "get_settings",
            lambda: _settings(enabled=True, rollout_pct=100),
        )

        def _explode(parent_job_id):
            raise RuntimeError("scheduler broken")

        monkeypatch.setattr(
            post_render_hook.refinement_service,
            "schedule_refinement",
            _explode,
        )
        post_render_hook.schedule_refinement_if_eligible(
            parent_job_id=uuid4(), org_id=uuid4()
        )
        assert "whisper_refine_hook_failed" in _captured_log_text(caplog, capsys)
