"""Daily USD ceiling for Whisper transcription.

DUPLICATED from ``app/modules/shorts_auto/llm/budget.py`` and
``app/modules/image_caption/engines/openai_client.py``. The note in
``shorts_auto/llm/budget.py:5-6`` flagged that consolidation should
happen "once a second feature uses it" — Whisper makes this the third
consumer, so consolidation into a shared ``app/lib/openai/budget.py``
is now overdue. Tracked as a follow-up to keep PR 1 strictly additive.

In-memory is correct for a single-replica api. Multi-replica deploys
need a Redis-backed tracker.
"""

from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass
from typing import Protocol


class BudgetExceededError(Exception):
    """Daily budget exhausted. Caller should skip refinement."""


class BudgetTracker(Protocol):
    def check_and_reserve(self, estimated_cost_usd: float) -> None: ...
    def record(self, actual_cost_usd: float) -> None: ...
    def release_reservation(self, estimated_cost_usd: float) -> None: ...
    def spent_today_usd(self) -> float: ...


def _today_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


@dataclass
class InMemoryBudgetTracker:
    """Thread-safe daily-USD counter with UTC midnight reset.

    Two-phase: ``check_and_reserve`` raises when projected spend
    (already-spent + reserved + this-call estimate) would exceed the
    daily ceiling; ``record`` releases the reservation and adds the
    actual post-call cost. The reservation prevents two concurrent
    calls from each seeing "we have headroom" and collectively
    blowing the budget.
    """

    daily_budget_usd: float
    _lock: threading.Lock = None  # type: ignore[assignment]
    _date: str = ""
    _spent_usd: float = 0.0
    _reserved_usd: float = 0.0

    def __post_init__(self) -> None:
        self._lock = threading.Lock()
        self._date = _today_utc()

    def _roll_day_if_needed(self) -> None:
        today = _today_utc()
        if today != self._date:
            self._date = today
            self._spent_usd = 0.0
            self._reserved_usd = 0.0

    def check_and_reserve(self, estimated_cost_usd: float) -> None:
        with self._lock:
            self._roll_day_if_needed()
            projected = self._spent_usd + self._reserved_usd + estimated_cost_usd
            if projected > self.daily_budget_usd:
                raise BudgetExceededError(
                    f"daily whisper budget exceeded: "
                    f"spent=${self._spent_usd:.4f} "
                    f"reserved=${self._reserved_usd:.4f} "
                    f"estimated_next=${estimated_cost_usd:.4f} "
                    f"limit=${self.daily_budget_usd:.2f}"
                )
            self._reserved_usd += estimated_cost_usd

    def record(self, actual_cost_usd: float) -> None:
        with self._lock:
            self._roll_day_if_needed()
            self._reserved_usd = max(0.0, self._reserved_usd - actual_cost_usd)
            self._spent_usd += actual_cost_usd

    def release_reservation(self, estimated_cost_usd: float) -> None:
        """Release a reservation without recording spend.

        Use when a reserved call fails before reaching the API (e.g.
        network error before upload). Without this, failed calls would
        leak reservations until UTC reset and starve future calls.
        """
        with self._lock:
            self._roll_day_if_needed()
            self._reserved_usd = max(0.0, self._reserved_usd - estimated_cost_usd)

    def spent_today_usd(self) -> float:
        with self._lock:
            self._roll_day_if_needed()
            return self._spent_usd
