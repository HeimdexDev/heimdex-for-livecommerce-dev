"""ProductAppearanceRepository — per-product appearance windows.

Append-only; re-running tracking on the same catalog entry inserts a
new batch keyed by ``tracker_version``. The active-only partial index
(``ix_product_appearances_catalog WHERE rejected_reason IS NULL``)
keeps the gallery query cheap as rejected rows accumulate.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.shorts_auto_product.models import ProductAppearance


class ProductAppearanceRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session: AsyncSession = session

    # ---------- read ----------

    async def list_active_by_catalog(
        self,
        *,
        org_id: UUID,
        catalog_entry_id: UUID,
    ) -> list[ProductAppearance]:
        """Active (non-rejected) appearances ordered chronologically —
        matches the stitching plan's chronological default."""
        stmt = (
            select(ProductAppearance)
            .where(
                ProductAppearance.catalog_entry_id == catalog_entry_id,
                ProductAppearance.org_id == org_id,
                ProductAppearance.rejected_reason.is_(None),
            )
            .order_by(ProductAppearance.window_start_ms.asc())
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_active(
        self,
        *,
        org_id: UUID,
        catalog_entry_id: UUID,
    ) -> int:
        rows = await self.list_active_by_catalog(
            org_id=org_id, catalog_entry_id=catalog_entry_id,
        )
        return len(rows)

    # ---------- write ----------

    async def bulk_insert(
        self,
        *,
        appearances: list[dict[str, Any]],
    ) -> list[ProductAppearance]:
        if not appearances:
            return []
        rows = [ProductAppearance(**fields) for fields in appearances]
        self.session.add_all(rows)
        await self.session.flush()
        return rows

    async def purge_for_catalog_and_tracker(
        self,
        *,
        catalog_entry_id: UUID,
        tracker_version: str,
    ) -> int:
        """Hard delete all appearances for a catalog entry written by a
        specific tracker version. Used when re-running tracking after
        a version bump — old rows would otherwise mix with the new
        batch since both are append-only.

        Hard delete (not soft) because tracker output is reconstructible
        — the canonical reference and SAM2 are deterministic given the
        same model versions, so there's no audit value to retaining
        stale tracks.
        """
        stmt = delete(ProductAppearance).where(
            ProductAppearance.catalog_entry_id == catalog_entry_id,
            ProductAppearance.tracker_version == tracker_version,
        )
        result = await self.session.execute(stmt)
        return int(result.rowcount or 0)
