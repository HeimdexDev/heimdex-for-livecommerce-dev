"""BM25 mention extraction over OpenSearch.

For a given video + catalog entry, finds scenes whose
``transcript_raw`` or ``scene_caption`` substring-match the
``llm_label`` or any ``spoken_aliases`` (PR 1b output).

Korean morphology: ``transcript_raw`` and ``scene_caption`` are
analyzed with the ``nori`` tokenizer in ``heimdex_scenes_v5``. The
``match`` query splits the search string on the same analyzer, so
``달심`` matches ``달심에``, ``달심과``, etc. without us hand-rolling
stems.

Loose-coupling: this module imports ONLY ``opensearchpy`` (external),
``app.config`` (top-level), and own-module symbols. It does NOT
import from ``app.modules.search.*`` — we construct an
``AsyncOpenSearch`` client inline rather than reuse
``app.modules.search.client.get_opensearch_client`` to keep
``shorts_auto_product`` from cross-module imports per CLAUDE.md.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.modules.shorts_auto_product.track_stt.errors import (
    MentionExtractionError,
)
from app.modules.shorts_auto_product.track_stt.models import MentionedScene

logger = logging.getLogger(__name__)


# Per-query result cap. With BM25 + 3-5 aliases, getting >150 hits on
# a single video means the search is over-matching (e.g., a generic
# alias like ``"이 패키지"`` is too broad). The assembler downstream
# will compress this set anyway via the gap-merge.
_DEFAULT_RESULT_CAP = 200

# Field-level boosts. Transcript_raw is the strongest signal —
# audio mentions are direct evidence the host is talking about the
# product. scene_caption is supplementary — VLM descriptions may
# mention the product even when the host talks about something
# else (e.g., a wide shot establishing the scene).
_TRANSCRIPT_BOOST = 3.0
_CAPTION_BOOST = 1.5
# Per-alias boost decays so that the canonical llm_label outranks
# auto-generated aliases. The strongest alias is the brand
# transliteration (e.g., "달심"); generic aliases ("이 주스") get a
# floor to keep them from dominating the score.
_LABEL_BOOST = 2.0
_ALIAS_HEAD_BOOST = 1.0
_ALIAS_TAIL_BOOST = 0.4


async def find_mentioned_scenes(
    *,
    os_client: Any,
    index_alias: str,
    org_id: UUID,
    video_id: str,
    llm_label: str,
    spoken_aliases: list[str],
    result_cap: int = _DEFAULT_RESULT_CAP,
) -> list[MentionedScene]:
    """Run a single BM25 query and return matched scenes.

    Args:
        os_client: An ``AsyncOpenSearch`` (or compatible mock).
        index_alias: e.g., ``"heimdex_scenes"``.
        org_id: Tenant guard — the doc id format is
            ``f"{org_id}:{scene_id}"`` and the ``org_id`` field is a
            ``keyword`` on every scene row. We filter on the field to
            keep cross-org leakage impossible at the query layer.
        video_id: The drive ``video_id`` string (e.g.
            ``"gd_05e7f957502e86cf"``), NOT the ``drive_files.id`` UUID.
        llm_label: From the catalog entry — the canonical search term.
        spoken_aliases: From ``catalog_entries.spoken_aliases``. May be
            empty (PR 1b backfill not yet run for this entry); the
            query falls back to ``llm_label`` only in that case.
        result_cap: Defensive cap on returned hits.

    Returns:
        ``MentionedScene[]`` ordered by OS ``_score`` descending. May
        be empty (caller checks and surfaces ``NoMentionsFoundError``).

    Raises:
        :class:`MentionExtractionError`: OS query failed.
    """

    query = _build_bm25_query(
        org_id=org_id,
        video_id=video_id,
        llm_label=llm_label,
        spoken_aliases=spoken_aliases,
    )

    try:
        response = await os_client.search(
            index=index_alias,
            body={
                "size": result_cap,
                "query": query,
                "_source": [
                    "scene_id",
                    "start_ms",
                    "end_ms",
                    "transcript_raw",
                    "scene_caption",
                ],
                "sort": [{"_score": "desc"}],
            },
        )
    except Exception as e:  # noqa: BLE001 — wrap-and-rethrow
        logger.warning(
            "stt_mention_extraction_os_failed",
            extra={
                "video_id": video_id,
                "org_id": str(org_id),
                "error": str(e)[:300],
            },
        )
        raise MentionExtractionError(f"OS search failed: {e}") from e

    hits = response.get("hits", {}).get("hits", [])
    scenes = [_hit_to_scene(h, llm_label, spoken_aliases) for h in hits]
    # OS returned them ranked by score; keep the order. Caller
    # may re-sort by start_ms in the assembler.
    logger.info(
        "stt_mention_extraction_completed",
        extra={
            "video_id": video_id,
            "org_id": str(org_id),
            "alias_count": len(spoken_aliases),
            "scene_count": len(scenes),
            "max_score": scenes[0].score if scenes else 0.0,
        },
    )
    return scenes


# ---------- internals ----------


def _build_bm25_query(
    *,
    org_id: UUID,
    video_id: str,
    llm_label: str,
    spoken_aliases: list[str],
) -> dict[str, Any]:
    """Build the OS query body. Pure function — easy to test."""
    should_clauses: list[dict[str, Any]] = []

    # ---- canonical label, both fields ----
    label_clean = (llm_label or "").strip()
    if label_clean:
        should_clauses.append({
            "match": {
                "transcript_raw": {
                    "query": label_clean,
                    "boost": _TRANSCRIPT_BOOST * _LABEL_BOOST,
                }
            }
        })
        should_clauses.append({
            "match": {
                "scene_caption": {
                    "query": label_clean,
                    "boost": _CAPTION_BOOST * _LABEL_BOOST,
                }
            }
        })

    # ---- aliases, decaying boost ----
    seen: set[str] = {label_clean.casefold()} if label_clean else set()
    for idx, raw_alias in enumerate(spoken_aliases or []):
        alias = (raw_alias or "").strip()
        if not alias:
            continue
        key = alias.casefold()
        if key in seen:
            continue
        seen.add(key)
        # First alias keeps the head boost; remainder share the tail.
        per_alias_boost = _ALIAS_HEAD_BOOST if idx == 0 else _ALIAS_TAIL_BOOST
        should_clauses.append({
            "match": {
                "transcript_raw": {
                    "query": alias,
                    "boost": _TRANSCRIPT_BOOST * per_alias_boost,
                }
            }
        })
        should_clauses.append({
            "match": {
                "scene_caption": {
                    "query": alias,
                    "boost": _CAPTION_BOOST * per_alias_boost,
                }
            }
        })

    return {
        "bool": {
            "must": [
                {"term": {"org_id": str(org_id)}},
                {"term": {"video_id": video_id}},
            ],
            "should": should_clauses,
            "minimum_should_match": 1 if should_clauses else 0,
        }
    }


def _hit_to_scene(
    hit: dict[str, Any],
    llm_label: str,
    spoken_aliases: list[str],
) -> MentionedScene:
    """Map one OS hit → MentionedScene. Pure function.

    ``matched_field`` is determined by which fields had non-empty text
    that contained any of the search tokens. We don't get
    per-clause-match data from OS without explain mode, so we re-run
    a substring check locally — cheap, deterministic, and good enough
    for the debug surface.
    """
    src = hit.get("_source", {}) or {}
    scene_id = str(src.get("scene_id", ""))
    start_ms = int(src.get("start_ms", 0) or 0)
    end_ms = int(src.get("end_ms", 0) or 0)
    score = float(hit.get("_score", 0.0) or 0.0)

    transcript = (src.get("transcript_raw") or "").strip()
    caption = (src.get("scene_caption") or "").strip()

    # Build the alias-set for substring re-check.
    tokens = [t for t in [llm_label, *spoken_aliases] if t]
    transcript_match = any(_contains_ci(transcript, t) for t in tokens)
    caption_match = any(_contains_ci(caption, t) for t in tokens)

    if transcript_match and caption_match:
        matched_field: str = "both"
    elif transcript_match:
        matched_field = "transcript_raw"
    elif caption_match:
        matched_field = "scene_caption"
    else:
        # OS scored it >0 (probably via nori stemming on a partial
        # token); we can't pin it to a specific field. Bias to
        # caption since transcript false-stems are rarer in practice.
        matched_field = "scene_caption"

    matched_aliases = [t for t in tokens if _contains_ci(transcript + " " + caption, t)]

    return MentionedScene(
        scene_id=scene_id,
        start_ms=start_ms,
        end_ms=end_ms,
        score=score,
        matched_field=matched_field,  # type: ignore[arg-type]
        matched_aliases=matched_aliases,
        transcript_text=transcript,
        caption_text=caption,
    )


def _contains_ci(haystack: str, needle: str) -> bool:
    """Case-insensitive substring check. Korean is case-invariant
    so ``casefold`` is a no-op there; matters for Latin aliases like
    ``"Dalsim"`` / ``"dalsim"`` / ``"DALSIM"``.
    """
    return needle.casefold() in haystack.casefold()
