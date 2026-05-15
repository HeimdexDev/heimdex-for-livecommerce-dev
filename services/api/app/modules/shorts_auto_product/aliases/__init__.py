"""Spoken-form alias generation for catalog entries (v0.15.0+).

Background: the auto-shorts product mode v2 STT-pivot replaces SAM2
visual tracking with mention extraction over OpenSearch
``transcript_raw`` / ``scene_caption``. The per-video catalog rows are
populated by ``product-enumerate-worker`` reading the brand off
on-screen packaging — but Korean livecommerce hosts pronounce /
abbreviate / categorize products differently. Without an alias layer
~33% of catalog entries return zero spoken mentions on the validation
video.

This module is the post-hoc generator: takes a catalog entry's
``canonical_crop_s3_key`` + ``llm_label``, asks gpt-4o-mini for 3-5
spoken-form aliases, persists them on the row. Runs as:

* a one-shot via ``app.cli.backfill_spoken_aliases`` for existing
  catalogs
* a fire-and-forget ``asyncio.create_task`` after the enumerate
  worker's ``/internal/products/.../complete`` callback (PR 2+)

Loose-coupling: this module imports only from
``heimdex_media_contracts.product``, ``app.modules.shorts_auto_product.*``
(own module), ``app.config``, ``app.storage.s3``, and ``openai``. It
does NOT import from ``app.modules.shorts_auto.*`` or
``heimdex_media_pipelines.*``.
"""

from app.modules.shorts_auto_product.aliases.errors import (
    AliasGenerationBudgetExceeded,
    AliasGenerationError,
    AliasGenerationRetryable,
    AliasGenerationTerminal,
)
from app.modules.shorts_auto_product.aliases.generator import (
    AliasGenerationResult,
    AliasGenerator,
)

__all__ = [
    "AliasGenerationBudgetExceeded",
    "AliasGenerationError",
    "AliasGenerationResult",
    "AliasGenerationRetryable",
    "AliasGenerationTerminal",
    "AliasGenerator",
]
