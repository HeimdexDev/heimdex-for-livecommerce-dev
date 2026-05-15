"""Add spoken_aliases + provenance to product_catalog_entries.

The auto-shorts product mode v2 STT-pivot replaces SAM2 visual tracking
with mention extraction over OpenSearch ``transcript_raw`` /
``scene_caption``. Per validation on ``gd_05e7f957502e86cf`` (the
handoff video, 9 catalog entries), 3 of 9 catalog ``llm_label`` strings
do not substring-match the host's spoken Korean — the catalog reads
the brand off the on-screen packaging, but Korean livecommerce hosts
pronounce / abbreviate / generic-categorize differently
(e.g. catalog ``"온리틀"`` ↔ host says ``"온리츄얼"`` /
``"올리주얼"``). Without an alias layer ~33% of catalog entries
return zero mentions and the wizard cannot find clips for them.

Three additive columns:

* ``spoken_aliases TEXT[]`` — the BM25 query terms. Empty default so
  v0.14.0 senders / pre-PR-1 rows round-trip cleanly. The contracts
  schema caps the field at 10 entries; the DB does NOT enforce a cap
  (it would have to be a CHECK on cardinality(...) which costs more
  than the schema's max_length=10 already enforces at the boundary).
* ``aliases_generated_at TIMESTAMPTZ`` — set by the backfill CLI when
  alias generation succeeds. ``NULL`` means "not yet attempted" — the
  CLI's selection query keys on this. ``NULL`` survives a generation
  attempt that returned an empty list (the LLM saw an unreadable
  image and correctly refused to guess); we don't want to retry that
  forever, so the CLI checks BOTH ``IS NULL`` AND
  ``aliases_prompt_version != current_version``.
* ``aliases_prompt_version TEXT`` — mirrors
  ``heimdex_media_contracts.product.AliasGenerationPrompt.VERSION``.
  Lets a future prompt bump target only stale rows for re-generation
  without re-running enumeration. Set in lockstep with
  ``aliases_generated_at``.

No index added. Aliases are read in JOIN with the catalog entry; the
existing ``ix_product_catalog_org_video`` partial index already drives
the per-video lookup. The STT-track BM25 query happens in OpenSearch,
not Postgres — Postgres only feeds aliases into the OS query at
construction time.

Plan: ``.claude/plans/shorts-auto-product-stt-pivot.md`` PR 1b.

Revision ID: 054_add_spoken_aliases
Revises: 053_recreate_active_index_with_wizard_stages
Create Date: 2026-05-06

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "054_add_spoken_aliases"
down_revision: str | None = "053_recreate_active_index_with_wizard_stages"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Three columns, all additive. The TEXT[] default of '{}' is what
    # makes existing rows usable without a backfill — they parse as
    # "no aliases yet, will fall back to llm_label only" in the
    # mention extractor. The provenance columns stay NULL on existing
    # rows so the backfill CLI's selection query
    # (``aliases_generated_at IS NULL OR aliases_prompt_version != :v``)
    # picks them up.
    op.execute("""
        ALTER TABLE product_catalog_entries
            ADD COLUMN IF NOT EXISTS spoken_aliases TEXT[] NOT NULL DEFAULT '{}',
            ADD COLUMN IF NOT EXISTS aliases_generated_at TIMESTAMPTZ,
            ADD COLUMN IF NOT EXISTS aliases_prompt_version TEXT
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE product_catalog_entries
            DROP COLUMN IF EXISTS aliases_prompt_version,
            DROP COLUMN IF EXISTS aliases_generated_at,
            DROP COLUMN IF EXISTS spoken_aliases
    """)
