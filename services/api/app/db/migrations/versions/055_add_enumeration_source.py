"""Add enumeration_source + first_mention_ms + example_quote.

The auto-shorts product mode v2 STT-pivot adds a parallel **STT-first
enumeration** path (gpt-4o-mini over the concatenated video transcript)
running alongside the existing vision enumerator. Catalog entries
discovered via the STT path have no canonical crop, no SigLIP2
embedding, and no prominence score — those fields are vision-only.

Three additive columns:

* ``enumeration_source TEXT NOT NULL DEFAULT 'vision'`` — provenance
  flag with a CHECK constraint locked to
  ``{'vision', 'stt', 'stt_xref', 'manifest', 'hybrid'}``. CHECK
  rather than a Postgres ENUM type sidesteps the
  ENUM-add-value-needs-transaction-per-migration footgun
  (``feedback_alembic_enum_add_value_pattern.md``) and lets us add a
  new source (``manifest`` is reserved for a user-supplied product
  list flow) without a coordinated env.py change.

* ``first_mention_ms BIGINT NULL`` — anchor for STT-source entries.
  Two uses: (1) ordering in the wizard catalog view (chronological by
  first mention, not insertion order); (2) Phase 5 visual back-fill
  optionally samples frames near this timestamp to populate a
  ``canonical_crop_s3_key`` post-hoc. NULL on vision-source entries
  (the vision path doesn't know when in time the host first mentioned
  the SKU).

* ``example_quote TEXT NULL`` — verbatim 1-2 sentence quote from the
  transcript that surfaced this product. Powers the wizard's
  provenance tooltip on STT-source cards (helps operators sanity-check
  what the LLM matched on). NULL on vision-source entries.

Plus, **drop NOT NULL** on the vision-only columns so STT-source
entries can be inserted without sentinel values:

* ``canonical_crop_s3_key`` — STT has no frame to crop
* ``canonical_video_id`` — same
* ``canonical_frame_idx`` — same
* ``canonical_bbox_{x,y,w,h}`` — same
* ``prominence_score`` — vision-specific concept (bbox area / clarity
  composite); no STT analog. ``enumeration_confidence`` stays
  NOT NULL — STT entries also have a confidence score from the
  transcript LLM call.

``enumeration_version`` and ``enumeration_prompt_version`` stay
NOT NULL. STT entries fill them with their own version strings
(``"stt-v1.0"`` and ``TranscriptEnumerationPrompt.VERSION``
respectively) — semantically these are the algorithm version + prompt
version regardless of source.

No new index. The existing ``ix_product_catalog_org_video`` partial
index already drives wizard reads. Provenance filtering by
``enumeration_source`` is rare enough (mostly admin / debugging) that a
dedicated index isn't justified at expected catalog cardinality.

Plan: ``.claude/plans/shorts-auto-product-stt-enum-2026-05-06.md``
PR 2 of 7.

Revision ID: 055_add_enumeration_source
Revises: 054_add_spoken_aliases
Create Date: 2026-05-06

"""
from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "055_add_enumeration_source"
down_revision: str | None = "054_add_spoken_aliases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_CHECK_CONSTRAINT_NAME = "ck_product_catalog_enumeration_source"
_ALLOWED_SOURCES = ("vision", "stt", "stt_xref", "manifest", "hybrid")


def upgrade() -> None:
    # Three additive columns. ``enumeration_source`` defaults to
    # 'vision' so every existing row inherits the correct provenance
    # without a backfill — the catalog before this migration was 100%
    # vision-enumerated.
    op.execute("""
        ALTER TABLE product_catalog_entries
            ADD COLUMN IF NOT EXISTS enumeration_source TEXT NOT NULL DEFAULT 'vision',
            ADD COLUMN IF NOT EXISTS first_mention_ms BIGINT,
            ADD COLUMN IF NOT EXISTS example_quote TEXT
    """)

    # CHECK constraint locks the allowed source values. Postgres does
    # not support ``ADD CONSTRAINT IF NOT EXISTS`` for table
    # constraints, so guard with pg_constraint lookup.
    op.execute(f"""
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = '{_CHECK_CONSTRAINT_NAME}'
            ) THEN
                ALTER TABLE product_catalog_entries
                    ADD CONSTRAINT {_CHECK_CONSTRAINT_NAME}
                    CHECK (enumeration_source IN
                        ('vision', 'stt', 'stt_xref', 'manifest', 'hybrid'));
            END IF;
        END $$;
    """)

    # Drop NOT NULL on the vision-only columns. STT-source entries are
    # inserted with NULL for every canonical_* field and prominence_score.
    # Existing rows are unaffected — they already have non-null values.
    op.execute("""
        ALTER TABLE product_catalog_entries
            ALTER COLUMN canonical_crop_s3_key DROP NOT NULL,
            ALTER COLUMN canonical_video_id DROP NOT NULL,
            ALTER COLUMN canonical_frame_idx DROP NOT NULL,
            ALTER COLUMN canonical_bbox_x DROP NOT NULL,
            ALTER COLUMN canonical_bbox_y DROP NOT NULL,
            ALTER COLUMN canonical_bbox_w DROP NOT NULL,
            ALTER COLUMN canonical_bbox_h DROP NOT NULL,
            ALTER COLUMN prominence_score DROP NOT NULL
    """)


def downgrade() -> None:
    # Re-add NOT NULL constraints. This will fail if any STT-source
    # rows exist (canonical_* fields are NULL on those). The
    # downgrade is best-effort for dev; production should never run
    # this once STT entries have been inserted.
    op.execute("""
        ALTER TABLE product_catalog_entries
            ALTER COLUMN prominence_score SET NOT NULL,
            ALTER COLUMN canonical_bbox_h SET NOT NULL,
            ALTER COLUMN canonical_bbox_w SET NOT NULL,
            ALTER COLUMN canonical_bbox_y SET NOT NULL,
            ALTER COLUMN canonical_bbox_x SET NOT NULL,
            ALTER COLUMN canonical_frame_idx SET NOT NULL,
            ALTER COLUMN canonical_video_id SET NOT NULL,
            ALTER COLUMN canonical_crop_s3_key SET NOT NULL
    """)

    op.execute(f"""
        ALTER TABLE product_catalog_entries
            DROP CONSTRAINT IF EXISTS {_CHECK_CONSTRAINT_NAME}
    """)

    op.execute("""
        ALTER TABLE product_catalog_entries
            DROP COLUMN IF EXISTS example_quote,
            DROP COLUMN IF EXISTS first_mention_ms,
            DROP COLUMN IF EXISTS enumeration_source
    """)
