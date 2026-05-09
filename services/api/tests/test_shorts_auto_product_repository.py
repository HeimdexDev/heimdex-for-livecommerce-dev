"""Repository-layer tests for ProductScanJobRepository.

Focus: SQL composition — the queries this repo emits are tenant-,
stage-, and mode-sensitive. A small WHERE-clause regression silently
mis-counts (cap query) or misses claimable rows (runner poll). These
tests compile the statements against the postgres dialect and assert
on the SQL text so the bug class can't recur.

Mock-based; no live DB. Integration tests against a real Postgres go
in a separate file marked ``integration``.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql

from app.modules.shorts_auto_product.repositories.job import (
    ProductScanJobRepository,
)


@pytest.fixture
def session():
    s = AsyncMock()
    s.add = MagicMock()
    return s


@pytest.fixture
def repo(session):
    return ProductScanJobRepository(session)


def _compile(stmt) -> str:
    """Compile a SQLAlchemy statement against the postgres dialect with
    literal binds so the resulting string can be grepped in tests.

    Postgres-specific because that's the deployment target; sqlite
    would also work but might differ on `!=` rendering.
    """
    return str(
        stmt.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )


def _make_count_result(value: int) -> MagicMock:
    """Build a mock SQLAlchemy Result that ``.scalar_one()`` returns
    ``value`` for. Mirrors the shape of count_active_for_org's caller."""
    result = MagicMock()
    result.scalar_one = MagicMock(return_value=value)
    return result


# ---------- count_active_for_org ----------


class TestCountActiveForOrg:
    """The per-org concurrency cap query.

    See ``.claude/plans/shorts-auto-product-cap-stuck-fix.md`` PR 1 for
    the design rationale. The cap counts user-initiated work units
    (``mode IN ('enumerate', 'scan_order')``) — NEVER ``render_child``,
    because a wizard scan_order with requested_count=N creates 1 parent
    + N children and the user's intent is a single work unit.
    """

    @pytest.mark.asyncio
    async def test_returns_int_from_scalar_one(self, repo, session):
        """Basic shape — mirrors blur_repository's count_active test."""
        session.execute = AsyncMock(return_value=_make_count_result(7))
        n = await repo.count_active_for_org(org_id=uuid4())
        assert n == 7
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_zero_returned_when_scalar_one_is_none(self, repo, session):
        """Defensive: ``or 0`` clause guards against a None from a
        broken DB row. Verify count returns 0, not None."""
        result = MagicMock()
        result.scalar_one = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=result)
        n = await repo.count_active_for_org(org_id=uuid4())
        assert n == 0

    @pytest.mark.asyncio
    async def test_where_clause_excludes_render_child_mode(self, repo, session):
        """The bug this PR fixes: the cap query MUST filter out
        render_child rows so a wizard fan-out of N children doesn't
        consume N+1 slots. Compile the stmt and grep for the predicate.
        """
        session.execute = AsyncMock(return_value=_make_count_result(0))
        await repo.count_active_for_org(org_id=uuid4())

        stmt = session.execute.await_args.args[0]
        sql = _compile(stmt)

        # The new filter — 'render_child' must appear in a NOT-equal
        # comparison. SQLAlchemy renders `!=` as `!=` in postgres
        # dialect.
        assert "'render_child'" in sql, (
            f"Expected the cap query to filter on mode != 'render_child', "
            f"but it does not appear in the compiled SQL:\n{sql}"
        )
        assert "mode" in sql, (
            f"Expected the cap query to reference the mode column:\n{sql}"
        )
        # Defensive: the comparison must be NOT-equal (we exclude
        # children), not equality (which would only count children).
        assert "!=" in sql or "<>" in sql, (
            f"Expected `mode != 'render_child'` (or <>), got:\n{sql}"
        )

    @pytest.mark.asyncio
    async def test_where_clause_filters_active_stages(self, repo, session):
        """Regression guard: cap query must still filter on
        ACTIVE_SCAN_STAGES (queued/enumerating/tracking/etc) — not
        accidentally count terminal rows like ``done`` or
        ``cancelled``."""
        session.execute = AsyncMock(return_value=_make_count_result(0))
        await repo.count_active_for_org(org_id=uuid4())

        stmt = session.execute.await_args.args[0]
        sql = _compile(stmt)

        # Spot-check: a couple of active stages must appear; no
        # terminal stage may.
        assert "'queued'" in sql
        assert "'fanned_out'" in sql
        assert "'done'" not in sql, (
            f"Cap query incorrectly references the terminal 'done' "
            f"stage:\n{sql}"
        )
        assert "'committed'" not in sql, (
            f"Cap query incorrectly references the terminal 'committed' "
            f"stage:\n{sql}"
        )
        assert "'cancelled'" not in sql, (
            f"Cap query incorrectly references the terminal 'cancelled' "
            f"stage:\n{sql}"
        )

    @pytest.mark.asyncio
    async def test_where_clause_filters_org(self, repo, session):
        """Tenant scoping: the cap is per-org. The org_id passed in
        MUST appear in the WHERE clause."""
        session.execute = AsyncMock(return_value=_make_count_result(0))
        org_id = uuid4()
        await repo.count_active_for_org(org_id=org_id)

        stmt = session.execute.await_args.args[0]
        sql = _compile(stmt)
        assert str(org_id) in sql, (
            f"org_id {org_id} not present in compiled SQL:\n{sql}"
        )
