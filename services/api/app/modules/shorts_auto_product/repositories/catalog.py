"""ProductCatalogRepository — per-video catalog rows for product mode v2.

Read paths are org-scoped. Worker write paths land via the internal
router's ``complete`` callback after Bearer auth + lease check; that
caller already validated org ownership through the job row.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.shorts_auto_product.models import ProductCatalogEntry


# Prefixes encoded in ``rejected_reason`` by the consolidation pipeline.
# ``has_consolidation_markers`` keys off these to make consolidation
# idempotent without adding a new column. Mirrored by
# ``consolidate.service`` when it formats the strings on write.
_CONSOLIDATION_DUPLICATE_PREFIX = "duplicate_of:"
_CONSOLIDATION_NON_SELLABLE_PREFIX = "non_sellable:"


class ProductCatalogRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session: AsyncSession = session

    # ---------- read ----------

    async def list_active_by_video(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
    ) -> list[ProductCatalogEntry]:
        """Return non-rejected catalog entries for ``(org, video)``,
        ordered by prominence then enumeration confidence (best-first
        for the gallery view).
        """
        stmt = (
            select(ProductCatalogEntry)
            .where(
                ProductCatalogEntry.org_id == org_id,
                ProductCatalogEntry.video_id == video_id,
                ProductCatalogEntry.rejected_at.is_(None),
            )
            .order_by(
                ProductCatalogEntry.prominence_score.desc(),
                ProductCatalogEntry.enumeration_confidence.desc(),
            )
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def get(
        self,
        *,
        org_id: UUID,
        entry_id: UUID,
    ) -> ProductCatalogEntry | None:
        """Tenant-guarded fetch. Cross-org access returns ``None`` —
        the router converts to 404 (NOT 403, to avoid info leak)."""
        stmt = select(ProductCatalogEntry).where(
            ProductCatalogEntry.id == entry_id,
            ProductCatalogEntry.org_id == org_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    async def get_by_id_resource_scoped(
        self, entry_id: UUID,
    ) -> ProductCatalogEntry | None:
        """Pattern B fetch: ``id``-only lookup that returns the row
        with its ``.org_id`` so ``resolve_resource_with_org`` can
        derive tenant context. NOT a default — Pattern A callers
        (``list_active_by_video``, ``get``) keep their org filter as
        the security boundary. Worker-facing endpoints with a path
        resource use this method via the shared helper.
        """
        stmt = select(ProductCatalogEntry).where(
            ProductCatalogEntry.id == entry_id,
        )
        return (await self.session.execute(stmt)).scalar_one_or_none()

    # ---------- write ----------

    async def bulk_insert(
        self,
        *,
        entries: list[dict[str, Any]],
    ) -> list[ProductCatalogEntry]:
        """Insert a batch of catalog rows produced by the worker.

        Each ``entries`` dict must contain every non-default column
        from :class:`ProductCatalogEntry`. The caller is the internal
        callback handler, which has already validated lease + org
        ownership against the parent ``ProductScanJob``.
        """
        if not entries:
            return []
        rows = [ProductCatalogEntry(**fields) for fields in entries]
        self.session.add_all(rows)
        await self.session.flush()
        return rows

    async def soft_reject(
        self,
        *,
        org_id: UUID,
        entry_id: UUID,
        reason: str,
    ) -> bool:
        """Mark a catalog entry as rejected.

        Returns ``True`` if a row was updated, ``False`` if no
        matching active row existed (already rejected, wrong org, etc.).
        """
        stmt = (
            update(ProductCatalogEntry)
            .where(
                ProductCatalogEntry.id == entry_id,
                ProductCatalogEntry.org_id == org_id,
                ProductCatalogEntry.rejected_at.is_(None),
            )
            .values(
                rejected_at=datetime.now(timezone.utc),
                rejected_reason=reason,
            )
        )
        result = await self.session.execute(stmt)
        return result.rowcount > 0

    # ---------- v0.15.0 — STT-pivot spoken aliases ----------

    async def find_entries_needing_aliases(
        self,
        *,
        current_prompt_version: str,
        org_id: UUID | None = None,
        video_id: UUID | None = None,
        limit: int = 1000,
    ) -> list[ProductCatalogEntry]:
        """Return active catalog entries that need alias generation.

        Selection: ``rejected_at IS NULL`` AND
        (``aliases_generated_at IS NULL`` OR
        ``aliases_prompt_version != current_prompt_version``). Both
        conditions are needed so a future prompt bump targets stale
        rows; the IS NULL covers freshly-inserted rows that the
        backfill hasn't touched yet.

        Org / video filters are optional. Backfill CLI uses ``org_id``
        only (org-wide); the future per-entry realtime hook will use
        ``id`` directly via :meth:`get_by_id_resource_scoped`.

        Caller orders by ``created_at`` to make backfills resumable —
        if the CLI dies mid-run, re-running picks up where it left off
        (already-aliased rows naturally drop out of the selection).
        """
        stmt = (
            select(ProductCatalogEntry)
            .where(
                ProductCatalogEntry.rejected_at.is_(None),
                (
                    ProductCatalogEntry.aliases_generated_at.is_(None)
                    | (
                        ProductCatalogEntry.aliases_prompt_version
                        != current_prompt_version
                    )
                ),
            )
            .order_by(ProductCatalogEntry.created_at.asc())
            .limit(limit)
        )
        if org_id is not None:
            stmt = stmt.where(ProductCatalogEntry.org_id == org_id)
        if video_id is not None:
            stmt = stmt.where(ProductCatalogEntry.video_id == video_id)
        return list((await self.session.execute(stmt)).scalars().all())

    async def update_aliases(
        self,
        *,
        entry_id: UUID,
        aliases: list[str],
        prompt_version: str,
    ) -> bool:
        """Persist alias generation result for one catalog entry.

        Idempotent: re-running with the same ``(aliases, prompt_version)``
        yields the same end state. The provenance pair
        (``aliases_generated_at``, ``aliases_prompt_version``) lets a
        future prompt bump distinguish "this row is fresh under v1.1"
        from "this row hasn't seen any alias generation yet".

        Not org-scoped because the backfill CLI iterates entries it
        has already loaded via :meth:`find_entries_needing_aliases`
        (which honors the org filter); a per-entry write does not need
        to re-validate the tenant boundary. The realtime hook (PR 2+)
        likewise calls this after re-fetching the entry within the
        request-scoped session.

        Returns ``True`` if a row was updated, ``False`` if the
        ``entry_id`` does not exist (caller should warn — usually
        means the row was deleted between selection and update,
        which is rare but worth noticing in CLI runs).
        """
        stmt = (
            update(ProductCatalogEntry)
            .where(ProductCatalogEntry.id == entry_id)
            .values(
                spoken_aliases=aliases,
                aliases_generated_at=datetime.now(timezone.utc),
                aliases_prompt_version=prompt_version,
            )
        )
        result = await self.session.execute(stmt)
        return bool(result.rowcount or 0)

    # ---------- v0.17.0 — post-enumeration consolidation ----------

    async def has_consolidation_markers(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
    ) -> bool:
        """Return True when this video's catalog has already been
        consolidated.

        We don't add a new column for the marker — instead, the
        consolidation pipeline writes ``rejected_reason`` strings with
        well-known prefixes (``duplicate_of:`` or ``non_sellable:``).
        The presence of even one such row is a sufficient signal: an
        un-consolidated video has only ``rescan_invalidated`` and
        worker-emitted rejection reasons.

        Cheap LIMIT 1 read; safe to call from the orchestrator before
        the LLM round-trip to short-circuit double-runs.
        """
        stmt = (
            select(ProductCatalogEntry.id)
            .where(
                ProductCatalogEntry.org_id == org_id,
                ProductCatalogEntry.video_id == video_id,
                ProductCatalogEntry.rejected_reason.is_not(None),
                (
                    ProductCatalogEntry.rejected_reason.like(
                        f"{_CONSOLIDATION_DUPLICATE_PREFIX}%",
                    )
                    | ProductCatalogEntry.rejected_reason.like(
                        f"{_CONSOLIDATION_NON_SELLABLE_PREFIX}%",
                    )
                ),
            )
            .limit(1)
        )
        return (await self.session.execute(stmt)).scalar_one_or_none() is not None

    async def apply_consolidation(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
        canonical_updates: list[dict[str, Any]],
        duplicate_rejections: list[dict[str, Any]],
        non_sellable_rejections: list[dict[str, Any]],
        prompt_version: str,
    ) -> tuple[int, int, int]:
        """Apply one consolidation result in a single transactional
        flush.

        Args:
            org_id, video_id: Tenant scope. Every UPDATE filters on
                both to keep the multi-tenant boundary intact.
            canonical_updates: Each dict has ``entry_id``,
                ``llm_label``, ``spoken_aliases``. Updates the
                canonical row's label + aliases in place; also bumps
                ``aliases_generated_at`` and ``aliases_prompt_version``
                so the backfill CLI won't pick this row up and
                overwrite our work.
            duplicate_rejections: Each dict has ``entry_id`` and
                ``canonical_entry_id``. Soft-rejects the row with
                reason ``duplicate_of:<canonical_uuid>``.
            non_sellable_rejections: Each dict has ``entry_id`` and
                ``category`` (host_equipment / ambient_object / ...).
                Soft-rejects with reason ``non_sellable:<category>``.
            prompt_version: Stamped onto
                ``aliases_prompt_version`` for canonical rows. Used as
                a goldens-eval gate downstream.

        Returns ``(canonicals_updated, duplicates_rejected,
        non_sellables_rejected)`` for observability. Caller is
        responsible for the commit boundary; this method only flushes.
        """
        if not canonical_updates and not duplicate_rejections and not non_sellable_rejections:
            return (0, 0, 0)

        now = datetime.now(timezone.utc)

        canonicals_updated = 0
        for cu in canonical_updates:
            stmt = (
                update(ProductCatalogEntry)
                .where(
                    ProductCatalogEntry.id == cu["entry_id"],
                    ProductCatalogEntry.org_id == org_id,
                    ProductCatalogEntry.video_id == video_id,
                    ProductCatalogEntry.rejected_at.is_(None),
                )
                .values(
                    llm_label=cu["llm_label"],
                    spoken_aliases=list(cu["spoken_aliases"]),
                    aliases_generated_at=now,
                    aliases_prompt_version=prompt_version,
                )
            )
            result = await self.session.execute(stmt)
            canonicals_updated += int(result.rowcount or 0)

        duplicates_rejected = 0
        for dr in duplicate_rejections:
            stmt = (
                update(ProductCatalogEntry)
                .where(
                    ProductCatalogEntry.id == dr["entry_id"],
                    ProductCatalogEntry.org_id == org_id,
                    ProductCatalogEntry.video_id == video_id,
                    ProductCatalogEntry.rejected_at.is_(None),
                )
                .values(
                    rejected_at=now,
                    rejected_reason=(
                        f"{_CONSOLIDATION_DUPLICATE_PREFIX}"
                        f"{dr['canonical_entry_id']}"
                    ),
                )
            )
            result = await self.session.execute(stmt)
            duplicates_rejected += int(result.rowcount or 0)

        non_sellables_rejected = 0
        for nr in non_sellable_rejections:
            stmt = (
                update(ProductCatalogEntry)
                .where(
                    ProductCatalogEntry.id == nr["entry_id"],
                    ProductCatalogEntry.org_id == org_id,
                    ProductCatalogEntry.video_id == video_id,
                    ProductCatalogEntry.rejected_at.is_(None),
                )
                .values(
                    rejected_at=now,
                    rejected_reason=(
                        f"{_CONSOLIDATION_NON_SELLABLE_PREFIX}"
                        f"{nr['category']}"
                    ),
                )
            )
            result = await self.session.execute(stmt)
            non_sellables_rejected += int(result.rowcount or 0)

        await self.session.flush()
        return (
            canonicals_updated,
            duplicates_rejected,
            non_sellables_rejected,
        )

    async def invalidate_video_catalog(
        self,
        *,
        org_id: UUID,
        video_id: UUID,
        reason: str = "rescan_invalidated",
    ) -> int:
        """Soft-reject every active catalog entry for a video — used
        by the force-rescan endpoint and by version-bump invalidation.

        Returns the number of rows transitioned. Existing appearances
        cascade naturally (still readable, but no longer surfaced via
        ``list_active_by_video``).
        """
        stmt = (
            update(ProductCatalogEntry)
            .where(
                ProductCatalogEntry.org_id == org_id,
                ProductCatalogEntry.video_id == video_id,
                ProductCatalogEntry.rejected_at.is_(None),
            )
            .values(
                rejected_at=datetime.now(timezone.utc),
                rejected_reason=reason,
            )
        )
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)
