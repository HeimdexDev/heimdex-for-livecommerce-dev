"""Daily cost ceiling for the LLM scene-picker.

Separate bucket from ``image_caption`` so a runaway caption backfill
doesn't starve auto-shorts (and vice versa). Both share the same
InMemoryBudgetTracker pattern; promote to a shared ``app/lib/openai/``
module only once a second feature uses it.

In-memory is correct for a single-replica api. Multi-replica requires
a Redis-backed tracker.
"""

from __future__ import annotations

import datetime as dt
import threading
from dataclasses import dataclass
from typing import Protocol


class BudgetExceededError(Exception):
    """Daily budget exhausted. Service falls back to pure scorer."""


class BudgetTracker(Protocol):
    def check_and_reserve(self, estimated_cost_usd: float) -> None: ...
    def record(self, actual_cost_usd: float) -> None: ...
    def spent_today_usd(self) -> float: ...


def _today_utc() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


@dataclass
class InMemoryBudgetTracker:
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
                    f"daily budget exceeded: "
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

    def spent_today_usd(self) -> float:
        with self._lock:
            self._roll_day_if_needed()
            return self._spent_usd
