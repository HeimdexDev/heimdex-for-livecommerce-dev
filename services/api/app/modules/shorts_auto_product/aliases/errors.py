"""Typed errors for alias generation.

Mirrors the ``image_caption.engines.base`` error hierarchy so a
consumer that already knows that contract picks up this one without
re-learning. Three classifications because the call chain has three
distinct failure modes:

* **Retryable** — transient (network, 5xx, rate-limit). Caller should
  back off and try again or skip this entry and continue the batch.
* **Terminal** — bad input (image unreadable, S3 NoSuchKey, schema
  validation refused) or 4xx that retries can't fix. Caller should
  log + skip the entry, mark it ``aliases_prompt_version=current``
  with ``spoken_aliases=[]`` so future runs don't keep retrying it.
* **Budget exceeded** — daily cap hit. Caller should stop the entire
  batch (not just this entry) and try tomorrow.

The CLI handles all three; the future realtime hook only cares about
budget (it fires-and-forgets on the others).
"""

from __future__ import annotations


class AliasGenerationError(Exception):
    """Base for every alias-generator failure."""


class AliasGenerationRetryable(AliasGenerationError):
    """Transient failure — backoff + retry, or skip and continue."""


class AliasGenerationTerminal(AliasGenerationError):
    """Permanent failure for THIS entry — skip and continue the batch."""


class AliasGenerationBudgetExceeded(AliasGenerationError):
    """Daily budget exhausted — stop the entire batch."""
