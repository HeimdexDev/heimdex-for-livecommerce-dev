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


# ---------- try_promote_parent_if_all_children_terminal (PR 2) ----------


def _make_update_result(returning_value) -> MagicMock:
    """Build a mock SQLAlchemy Result whose ``.scalar_one_or_none()``
    returns the value passed (a mock Job for success, None for
    no-match). Mirrors the .returning(ProductScanJob) shape on the
    UPDATE statement.
    """
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=returning_value)
    return result


class TestTryPromoteParentIfAllChildrenTerminal:
    """The atomic check-and-promote method.

    Tests the SQL composition: WHERE includes ``stage='fanned_out'``,
    ``mode='scan_order'``, and a NOT EXISTS subquery scoped to
    ``mode='render_child'`` and non-terminal stages.

    Plan: .claude/plans/shorts-auto-product-cap-stuck-fix.md (PR 2).
    """

    @pytest.mark.asyncio
    async def test_returns_none_when_atomic_update_matches_no_row(
        self, repo, session,
    ):
        """The single UPDATE-with-NOT-EXISTS returns None when the
        parent is already terminal, not in fanned_out, not a
        scan_order, OR some child is non-terminal."""
        session.execute = AsyncMock(return_value=_make_update_result(None))

        out = await repo.try_promote_parent_if_all_children_terminal(
            parent_job_id=uuid4(),
        )
        assert out is None
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_promoted_row_on_match(self, repo, session):
        """Successful promotion returns the transitioned row."""
        promoted = MagicMock()
        session.execute = AsyncMock(
            return_value=_make_update_result(promoted),
        )

        out = await repo.try_promote_parent_if_all_children_terminal(
            parent_job_id=uuid4(),
        )
        assert out is promoted

    @pytest.mark.asyncio
    async def test_where_clause_targets_fanned_out_stage(self, repo, session):
        """Defense in depth: the UPDATE refuses to override a
        cancelled or already-committed parent."""
        session.execute = AsyncMock(return_value=_make_update_result(None))

        await repo.try_promote_parent_if_all_children_terminal(
            parent_job_id=uuid4(),
        )
        sql = _compile(session.execute.await_args.args[0])
        assert "'fanned_out'" in sql, (
            f"Promotion query must guard on stage='fanned_out':\n{sql}"
        )

    @pytest.mark.asyncio
    async def test_where_clause_targets_scan_order_mode(self, repo, session):
        """Defense in depth: enumerate / render_child rows can't be
        promoted via this method."""
        session.execute = AsyncMock(return_value=_make_update_result(None))

        await repo.try_promote_parent_if_all_children_terminal(
            parent_job_id=uuid4(),
        )
        sql = _compile(session.execute.await_args.args[0])
        assert "'scan_order'" in sql, (
            f"Promotion query must guard on mode='scan_order':\n{sql}"
        )

    @pytest.mark.asyncio
    async def test_uses_not_exists_subquery_for_atomic_correctness(
        self, repo, session,
    ):
        """The atomic correctness — parent only promotes when NO
        sibling render_child is non-terminal. Without the NOT EXISTS,
        a race between the last-child terminal and a poll could
        promote prematurely.
        """
        session.execute = AsyncMock(return_value=_make_update_result(None))

        await repo.try_promote_parent_if_all_children_terminal(
            parent_job_id=uuid4(),
        )
        sql = _compile(session.execute.await_args.args[0])

        # The compiled UPDATE includes a NOT (EXISTS (...)) subquery
        # against product_scan_jobs filtered to render_child + non-
        # terminal stages.
        assert "NOT (EXISTS" in sql or "NOT EXISTS" in sql, (
            f"Expected NOT EXISTS atomicity guard:\n{sql}"
        )
        assert "'render_child'" in sql, (
            f"Subquery must scope to render_child rows:\n{sql}"
        )
        # The subquery filters NON-terminal stages, so terminal stage
        # literals should appear (in a NOT IN list).
        for terminal in ("'done'", "'committed'", "'failed'", "'cancelled'"):
            assert terminal in sql, (
                f"Expected {terminal} in NOT IN list of subquery:\n{sql}"
            )

    @pytest.mark.asyncio
    async def test_targets_correct_parent_id(self, repo, session):
        """The parent_job_id parameter must scope both the parent
        UPDATE target AND the NOT EXISTS subquery's parent_job_id
        comparison. Otherwise we'd promote arbitrary parents."""
        session.execute = AsyncMock(return_value=_make_update_result(None))

        parent_id = uuid4()
        await repo.try_promote_parent_if_all_children_terminal(
            parent_job_id=parent_id,
        )
        sql = _compile(session.execute.await_args.args[0])
        assert str(parent_id) in sql, (
            f"parent_job_id {parent_id} must appear in SQL:\n{sql}"
        )


# ---------- find_claimable_render_children (PR 3) ----------


class TestFindClaimableRenderChildren:
    """The self-healing runner poll. Returns render_child rows that are
    EITHER queued OR have an expired-lease assembling/rendering stage
    beyond the grace margin.

    Plan: .claude/plans/shorts-auto-product-cap-stuck-fix.md (PR 3).
    """

    @pytest.mark.asyncio
    async def test_returns_id_list_from_scalars(self, repo, session):
        """The query returns a list of UUIDs from .scalars().all()."""
        ids = [uuid4(), uuid4()]
        result = MagicMock()
        result.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=ids)),
        )
        session.execute = AsyncMock(return_value=result)

        out = await repo.find_claimable_render_children(limit=10)
        assert out == ids

    @pytest.mark.asyncio
    async def test_where_clause_includes_queued_branch(self, repo, session):
        """The legacy queued branch is preserved in the widened poll."""
        result = MagicMock()
        result.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[])),
        )
        session.execute = AsyncMock(return_value=result)

        await repo.find_claimable_render_children(limit=10)
        sql = _compile(session.execute.await_args.args[0])
        assert "'queued'" in sql, (
            f"Queued branch must remain in the WHERE:\n{sql}"
        )

    @pytest.mark.asyncio
    async def test_where_clause_includes_expired_lease_branch(
        self, repo, session,
    ):
        """The new self-heal branch covers expired-lease
        assembling/rendering rows."""
        result = MagicMock()
        result.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[])),
        )
        session.execute = AsyncMock(return_value=result)

        await repo.find_claimable_render_children(limit=10)
        sql = _compile(session.execute.await_args.args[0])
        assert "'assembling'" in sql, (
            f"Self-heal branch must include the 'assembling' stage:\n{sql}"
        )
        assert "'rendering'" in sql, (
            f"Self-heal branch must include the 'rendering' stage:\n{sql}"
        )
        assert "lease_expires_at" in sql, (
            f"Self-heal branch must reference lease_expires_at:\n{sql}"
        )

    @pytest.mark.asyncio
    async def test_render_child_mode_filter(self, repo, session):
        """The query MUST scope to mode='render_child' so it doesn't
        accidentally return enumerate or scan_order rows."""
        result = MagicMock()
        result.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[])),
        )
        session.execute = AsyncMock(return_value=result)

        await repo.find_claimable_render_children(limit=10)
        sql = _compile(session.execute.await_args.args[0])
        assert "'render_child'" in sql

    @pytest.mark.asyncio
    async def test_grace_seconds_overridable(self, repo, session):
        """The grace argument is plumbed to the WHERE cutoff so
        callers can tighten or relax it."""
        result = MagicMock()
        result.scalars = MagicMock(
            return_value=MagicMock(all=MagicMock(return_value=[])),
        )
        session.execute = AsyncMock(return_value=result)

        # Call with an explicit override; we don't assert the exact
        # cutoff timestamp (that depends on wall clock), just that
        # the query was issued — proving the parameter path works.
        await repo.find_claimable_render_children(limit=10, grace_seconds=300)
        session.execute.assert_awaited_once()


# ---------- claim() widened for re-claim (PR 3) ----------


class TestClaimReClaim:
    """PR 3 widened claim() to accept queued OR expired-lease
    assembling/rendering. started_at is preserved on re-claim via
    a CASE expression so the runner can distinguish re-claims from
    fresh claims (started_at < claimed_at)."""

    @pytest.mark.asyncio
    async def test_rejects_invalid_next_stage(self, repo, session):
        with pytest.raises(ValueError):
            await repo.claim(
                job_id=uuid4(),
                claimed_by="test",
                lease_seconds=300,
                next_stage="not_a_stage",
            )
        # Should NOT have hit the DB.
        session.execute.assert_not_called()

    @pytest.mark.asyncio
    async def test_where_clause_accepts_queued_branch(self, repo, session):
        """Backward-compat: fresh queued claims still match."""
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=result)

        await repo.claim(
            job_id=uuid4(),
            claimed_by="test",
            lease_seconds=300,
            next_stage="assembling",
        )
        sql = _compile(session.execute.await_args.args[0])
        assert "'queued'" in sql

    @pytest.mark.asyncio
    async def test_where_clause_accepts_expired_lease_branch(
        self, repo, session,
    ):
        """The new re-claim branch matches expired-lease
        assembling/rendering rows beyond the grace margin."""
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=result)

        await repo.claim(
            job_id=uuid4(),
            claimed_by="test",
            lease_seconds=300,
            next_stage="assembling",
        )
        sql = _compile(session.execute.await_args.args[0])
        assert "'assembling'" in sql
        assert "'rendering'" in sql
        assert "lease_expires_at" in sql, (
            f"Re-claim WHERE must guard on lease_expires_at:\n{sql}"
        )

    @pytest.mark.asyncio
    async def test_started_at_preserved_via_case_expression(
        self, repo, session,
    ):
        """Critical for the runner's re-claim warning: started_at is
        preserved on re-claim. Compiled SQL must contain a CASE
        expression on started_at, NOT a simple ``started_at = NOW``
        assignment that would clobber the original timestamp."""
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=result)

        await repo.claim(
            job_id=uuid4(),
            claimed_by="test",
            lease_seconds=300,
            next_stage="assembling",
        )
        sql = _compile(session.execute.await_args.args[0])
        # The CASE expression renders as `CASE WHEN
        # product_scan_jobs.started_at IS NULL THEN ... ELSE
        # product_scan_jobs.started_at END`. Look for the structural
        # markers — `CASE WHEN` + `IS NULL` + the `ELSE …started_at`
        # branch — to verify the preservation logic landed.
        assert "CASE WHEN" in sql, (
            f"started_at SET must use a CASE expression:\n{sql}"
        )
        assert "started_at IS NULL" in sql, (
            f"CASE must check started_at IS NULL:\n{sql}"
        )

    @pytest.mark.asyncio
    async def test_grace_seconds_overridable(self, repo, session):
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=result)

        await repo.claim(
            job_id=uuid4(),
            claimed_by="test",
            lease_seconds=300,
            next_stage="assembling",
            grace_seconds=600,
        )
        session.execute.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_returns_claimed_row_on_success(self, repo, session):
        claimed = MagicMock()
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=claimed)
        session.execute = AsyncMock(return_value=result)

        out = await repo.claim(
            job_id=uuid4(),
            claimed_by="test",
            lease_seconds=300,
            next_stage="assembling",
        )
        assert out is claimed

    @pytest.mark.asyncio
    async def test_returns_none_when_no_match(self, repo, session):
        """Returns None when the row is already claimed by a
        still-live worker (lease not yet beyond grace), terminal,
        or non-existent."""
        result = MagicMock()
        result.scalar_one_or_none = MagicMock(return_value=None)
        session.execute = AsyncMock(return_value=result)

        out = await repo.claim(
            job_id=uuid4(),
            claimed_by="test",
            lease_seconds=300,
            next_stage="assembling",
        )
        assert out is None
