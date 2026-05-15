"""Budget tracker behaviour for Whisper transcription."""

from __future__ import annotations

import pytest

from app.lib.whisper_transcribe import budget as budget_module
from app.lib.whisper_transcribe.budget import (
    BudgetExceededError,
    InMemoryBudgetTracker,
)


class TestInMemoryBudgetTracker:
    def test_starts_at_zero_spent(self) -> None:
        t = InMemoryBudgetTracker(daily_budget_usd=1.0)
        assert t.spent_today_usd() == 0.0

    def test_check_and_reserve_under_budget(self) -> None:
        t = InMemoryBudgetTracker(daily_budget_usd=1.0)
        t.check_and_reserve(0.5)  # no raise

    def test_reservations_accumulate(self) -> None:
        t = InMemoryBudgetTracker(daily_budget_usd=1.0)
        t.check_and_reserve(0.4)
        t.check_and_reserve(0.4)  # 0.8 reserved, fits
        with pytest.raises(BudgetExceededError, match="exceeded"):
            t.check_and_reserve(0.4)  # 1.2 would exceed

    def test_record_increments_spent(self) -> None:
        t = InMemoryBudgetTracker(daily_budget_usd=1.0)
        t.check_and_reserve(0.3)
        t.record(0.25)
        assert t.spent_today_usd() == pytest.approx(0.25)

    def test_record_releases_reservation(self) -> None:
        t = InMemoryBudgetTracker(daily_budget_usd=1.0)
        t.check_and_reserve(0.5)
        t.record(0.5)
        # Reservation released, full budget available again minus spent
        t.check_and_reserve(0.4)  # 0.5 spent + 0.4 reserved = 0.9, fits
        with pytest.raises(BudgetExceededError):
            t.check_and_reserve(0.2)  # 0.5 + 0.4 + 0.2 = 1.1 exceeds

    def test_release_reservation_does_not_count_as_spend(self) -> None:
        """Failed pre-call must not leak reservation OR add to spend."""
        t = InMemoryBudgetTracker(daily_budget_usd=1.0)
        t.check_and_reserve(0.5)
        t.release_reservation(0.5)
        assert t.spent_today_usd() == 0.0
        # Full budget available again
        t.check_and_reserve(0.9)

    def test_release_reservation_clamps_at_zero(self) -> None:
        """Releasing more than reserved must not make _reserved go negative."""
        t = InMemoryBudgetTracker(daily_budget_usd=1.0)
        t.check_and_reserve(0.2)
        t.release_reservation(1.0)  # over-release
        # Subsequent reserve uses only the actually-spent amount
        t.check_and_reserve(0.99)

    def test_exact_budget_match_succeeds(self) -> None:
        t = InMemoryBudgetTracker(daily_budget_usd=1.0)
        t.check_and_reserve(1.0)  # exactly at limit
        # One cent over fails
        with pytest.raises(BudgetExceededError):
            t.check_and_reserve(0.01)

    def test_zero_budget_blocks_immediately(self) -> None:
        t = InMemoryBudgetTracker(daily_budget_usd=0.0)
        with pytest.raises(BudgetExceededError):
            t.check_and_reserve(0.0001)

    def test_utc_reset_zeroes_spent_and_reserved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Day 1
        monkeypatch.setattr(budget_module, "_today_utc", lambda: "2026-05-06")
        t = InMemoryBudgetTracker(daily_budget_usd=1.0)
        t.check_and_reserve(0.6)
        t.record(0.5)
        assert t.spent_today_usd() == pytest.approx(0.5)

        # Roll to day 2 — both spent and reserved reset on next call.
        monkeypatch.setattr(budget_module, "_today_utc", lambda: "2026-05-07")
        assert t.spent_today_usd() == 0.0
        # Full budget available
        t.check_and_reserve(1.0)

    def test_independent_instances_have_separate_buckets(self) -> None:
        a = InMemoryBudgetTracker(daily_budget_usd=1.0)
        b = InMemoryBudgetTracker(daily_budget_usd=1.0)
        a.check_and_reserve(0.9)
        a.record(0.9)
        # b is unaffected
        assert b.spent_today_usd() == 0.0
        b.check_and_reserve(1.0)


class TestBudgetExceededError:
    def test_message_includes_amounts(self) -> None:
        t = InMemoryBudgetTracker(daily_budget_usd=1.0)
        t.check_and_reserve(0.6)
        t.record(0.6)
        try:
            t.check_and_reserve(0.5)
        except BudgetExceededError as e:
            msg = str(e)
            assert "spent=$0.6000" in msg
            assert "limit=$1.00" in msg
        else:
            pytest.fail("expected BudgetExceededError")
