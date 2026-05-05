"""Unit-scope regression tests for migration 055 + model changes.

PR 2 of the STT-first enumeration plan
(``.claude/plans/shorts-auto-product-stt-enum-2026-05-06.md``):

* Migration ``055_add_enumeration_source`` adds three columns to
  ``product_catalog_entries`` (``enumeration_source``,
  ``first_mention_ms``, ``example_quote``), a CHECK constraint locking
  ``enumeration_source`` values, and drops NOT NULL on the vision-only
  columns so STT-source rows can be inserted.

* The SQLAlchemy ``ProductCatalogEntry`` model is updated to mirror.

These tests are unit-scope (no Postgres) — DB CHECK enforcement is
deferred to integration tests like every other catalog migration in
this repo. The smoke-checks here guard against the most common drift
modes: missing column on the model, wrong nullability, wrong type,
revision/down_revision string drift, CHECK-allowlist drift between
the migration body and the documented set.

Run locally:

    cd services/api && source .venv/bin/activate && pytest \\
        tests/test_shorts_auto_product_enumeration_source.py
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

from sqlalchemy import BigInteger, Text

from app.modules.shorts_auto_product.models import ProductCatalogEntry


# ---------- helpers ----------


def _column(name: str):
    return ProductCatalogEntry.__table__.columns[name]


def _load_migration():
    """Load migration 055 by file path.

    Alembic migration filenames start with a digit so they aren't
    valid Python module names. Use ``importlib.util.spec_from_file_location``
    to load it directly. The migration is import-safe (no DB ops at
    import time — those run inside ``upgrade()`` / ``downgrade()``).
    """
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "app" / "db" / "migrations" / "versions"
        / "055_add_enumeration_source.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_migration_055", migration_path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------- migration metadata ----------


def test_migration_055_revision_id():
    m = _load_migration()
    assert m.revision == "055_add_enumeration_source"


def test_migration_055_down_revision_chains_to_054():
    m = _load_migration()
    # Wrong down_revision = silent skip on `alembic upgrade head`.
    assert m.down_revision == "054_add_spoken_aliases"


def test_migration_055_check_constraint_allowlist_locked():
    """The CHECK constraint allowlist drives the
    ``enumeration_source`` provenance enum. Drift between the
    migration body, the plan, and the wizard's badge mapping is a
    runtime bug — guard the literal here.
    """
    m = _load_migration()
    assert m._ALLOWED_SOURCES == (
        "vision", "stt", "stt_xref", "manifest", "hybrid",
    )
    assert m._CHECK_CONSTRAINT_NAME == "ck_product_catalog_enumeration_source"


def test_migration_055_upgrade_drops_not_null_on_vision_only_columns():
    """STT-source rows must be insertable with NULL for every
    vision-only column. The plan locks this list — if it changes,
    the wizard's STT-source rendering needs corresponding updates.
    """
    m = _load_migration()
    upgrade_src = m.upgrade.__code__.co_consts
    upgrade_text = " ".join(c for c in upgrade_src if isinstance(c, str))
    for col in (
        "canonical_crop_s3_key",
        "canonical_video_id",
        "canonical_frame_idx",
        "canonical_bbox_x",
        "canonical_bbox_y",
        "canonical_bbox_w",
        "canonical_bbox_h",
        "prominence_score",
    ):
        assert f"{col} DROP NOT NULL" in upgrade_text, (
            f"migration 055 must drop NOT NULL on {col}"
        )


def test_migration_055_upgrade_does_not_touch_enumeration_confidence():
    """``enumeration_confidence`` STAYS NOT NULL — STT entries also
    have a confidence score from the transcript LLM call. Defending
    against an over-eager edit that nullables the wrong column.
    """
    m = _load_migration()
    upgrade_text = " ".join(
        c for c in m.upgrade.__code__.co_consts if isinstance(c, str)
    )
    assert "enumeration_confidence DROP NOT NULL" not in upgrade_text


# ---------- model: new columns ----------


def test_model_has_enumeration_source_column():
    col = _column("enumeration_source")
    assert isinstance(col.type, Text)
    assert col.nullable is False
    # Server default keeps existing rows valid post-migration without
    # a backfill. Pre-PR-2 catalog was 100% vision-enumerated.
    assert col.server_default is not None


def test_model_has_first_mention_ms_column():
    col = _column("first_mention_ms")
    assert isinstance(col.type, BigInteger)
    # NULL on vision-source rows; the vision path doesn't know when
    # in time the host first mentioned the SKU.
    assert col.nullable is True


def test_model_has_example_quote_column():
    col = _column("example_quote")
    assert isinstance(col.type, Text)
    assert col.nullable is True


# ---------- model: vision-only columns now nullable ----------


def test_model_canonical_crop_s3_key_is_nullable():
    """STT-source rows have no canonical crop. Migration 055 dropped
    the NOT NULL; the model's type hint must mirror.
    """
    assert _column("canonical_crop_s3_key").nullable is True


def test_model_canonical_video_id_is_nullable():
    assert _column("canonical_video_id").nullable is True


def test_model_canonical_frame_idx_is_nullable():
    assert _column("canonical_frame_idx").nullable is True


def test_model_canonical_bbox_columns_all_nullable():
    for axis in ("x", "y", "w", "h"):
        assert _column(f"canonical_bbox_{axis}").nullable is True, (
            f"canonical_bbox_{axis} must be nullable for STT-source rows"
        )


def test_model_prominence_score_is_nullable():
    """Vision-only concept (bbox area / clarity composite) — no STT
    analog, so STT rows are inserted with NULL.
    """
    assert _column("prominence_score").nullable is True


# ---------- model: invariants that must NOT regress ----------


def test_model_enumeration_confidence_still_required():
    """The plan keeps ``enumeration_confidence`` NOT NULL because the
    transcript LLM also returns a confidence score. Drift here would
    let half-populated rows in.
    """
    assert _column("enumeration_confidence").nullable is False


def test_model_llm_label_still_required():
    """Both vision and STT paths emit an ``llm_label``."""
    assert _column("llm_label").nullable is False


def test_model_enumeration_version_still_required():
    """Both paths emit a version string (``"v1.0"`` for vision,
    ``"stt-v1.0"`` for STT). NULL would break the version-drift
    detection logic in the API → worker handshake.
    """
    assert _column("enumeration_version").nullable is False


def test_model_enumeration_prompt_version_still_required():
    """Mirrors the contracts schema — both paths persist whichever
    prompt VERSION produced the row.
    """
    assert _column("enumeration_prompt_version").nullable is False


def test_model_v015_alias_columns_unchanged():
    """Migration 054 columns (``spoken_aliases``,
    ``aliases_generated_at``, ``aliases_prompt_version``) must not
    have shifted — guard against a bad merge that touches the
    earlier migration's surface.
    """
    aliases = _column("spoken_aliases")
    assert aliases.nullable is False
    # server_default '{}' from migration 054
    assert aliases.server_default is not None

    assert _column("aliases_generated_at").nullable is True
    assert _column("aliases_prompt_version").nullable is True
