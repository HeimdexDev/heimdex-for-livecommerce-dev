"""Load and serialize a video's full transcript for the LLM enumerator.

Queries OpenSearch ``heimdex_scenes`` for every scene of a single
video, orders by ``start_ms`` ascending, drops scenes with empty
``transcript_raw``, and emits a single concatenated string with
``[mm:ss]`` timestamp markers — the exact format the
:class:`TranscriptEnumerationPrompt.USER_TEMPLATE` expects.

Returns the serialized transcript + a count of scenes consumed. The
caller (:mod:`service`) checks for empty results and short-circuits
to :class:`TranscriptUnavailableError` BEFORE making the LLM call —
spending OpenAI tokens to enumerate over an empty transcript is pure
waste.

Loose-coupling: imports ONLY ``opensearchpy`` (already a transitive
api dependency), :mod:`app.config`, and own-module symbols. Mirrors
``track_stt.mention_extractor``'s OS access pattern so a future
refactor that moves OS access into a shared helper updates both
sides at once.
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from app.modules.shorts_auto_product.enumerate_stt.errors import (
    TranscriptUnavailableError,
)

logger = logging.getLogger(__name__)


# Per-query cap. The hardest livecommerce video we've seen is ~3hr
# with scenes every 8-12s — call it ~1500 scenes worst case. The
# 5000 cap is a defensive ceiling that won't truncate any real
# video; pagination would be the right fix if a future video class
# blows past this, but is overkill today.
_MAX_SCENES_PER_QUERY = 5000

# Rough char→token ratio for gpt-4o-mini on Korean. The actual
# tokenizer is roughly 1 token per 1.5 Korean chars (BPE on UTF-8),
# but English / Latin run higher (1 token per ~4 chars). The
# transcript truncation is a guardrail, not a tight budget — the
# ``AUTO_SHORTS_PRODUCT_V2_STT_ENUM_MAX_TRANSCRIPT_TOKENS`` env var
# is the upstream limit; this loader applies a char-based proxy
# tuned for Korean (worst case).
_KOREAN_CHARS_PER_TOKEN = 1.5


def _format_timestamp(start_ms: int) -> str:
    """``[mm:ss]`` formatter mirroring the prompt's USER_TEMPLATE.

    Pure function. Hours-long videos render as ``[mm:ss]`` with
    minutes >= 60 (e.g. ``[127:33]``) — the LLM correctly interprets
    that as 2hr07m33s; switching to ``[hh:mm:ss]`` would force a
    prompt-version bump and we don't have a calibrated reason to.
    """
    if start_ms < 0:
        start_ms = 0
    total_seconds = start_ms // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"[{minutes:02d}:{seconds:02d}]"


async def load_transcript(
    *,
    os_client: Any,
    index_alias: str,
    org_id: UUID,
    video_id: str,
    max_tokens: int,
) -> tuple[str, int]:
    """Fetch + serialize the full transcript for one video.

    Args:
        os_client: ``AsyncOpenSearch`` (or compatible mock).
        index_alias: e.g., ``"heimdex_scenes"``.
        org_id: Tenant guard. Filtered into the OS query as
            ``term: {"org_id": str(org_id)}`` so cross-org leakage
            is impossible at the query layer.
        video_id: Drive ``video_id`` string (e.g.
            ``"gd_05e7f957502e86cf"``), NOT the ``drive_files.id``
            UUID. Same convention as ``track_stt.mention_extractor``.
        max_tokens: Upstream guardrail from
            ``AUTO_SHORTS_PRODUCT_V2_STT_ENUM_MAX_TRANSCRIPT_TOKENS``.
            Char-cap derived as ``max_tokens *
            _KOREAN_CHARS_PER_TOKEN`` so a Korean transcript can't
            sneak past the token limit.

    Returns:
        ``(serialized_transcript, scene_count)`` — newline-separated
        ``[mm:ss] {text}`` lines, ordered chronologically. Truncation
        is silent — only scenes that fully fit appear; partial-line
        truncation would corrupt the timestamp marker the LLM relies
        on for ``first_mention_ms``.

    Raises:
        :class:`TranscriptUnavailableError`: zero scenes had non-empty
            ``transcript_raw``. Distinct from "video has no scenes at
            all" (which would also raise this — same caller behavior).
    """
    response = await os_client.search(
        index=index_alias,
        body={
            "size": _MAX_SCENES_PER_QUERY,
            "query": {
                "bool": {
                    "must": [
                        {"term": {"org_id": str(org_id)}},
                        {"term": {"video_id": video_id}},
                    ],
                },
            },
            "_source": ["scene_id", "start_ms", "transcript_raw"],
            "sort": [{"start_ms": "asc"}],
        },
    )

    hits = response.get("hits", {}).get("hits", []) or []

    # Rough char cap derived from the upstream token limit.
    char_cap = int(max_tokens * _KOREAN_CHARS_PER_TOKEN)

    lines: list[str] = []
    char_total = 0
    consumed = 0
    truncated = False

    for hit in hits:
        src = hit.get("_source", {}) or {}
        transcript = (src.get("transcript_raw") or "").strip()
        if not transcript:
            # Skip silent / unenriched scenes. The line marker would
            # still cost a few tokens and surface no information.
            continue
        start_ms = int(src.get("start_ms", 0) or 0)
        line = f"{_format_timestamp(start_ms)} {transcript}"
        # Account for the newline that joins lines below.
        candidate_len = len(line) + 1
        if char_total + candidate_len > char_cap:
            truncated = True
            break
        lines.append(line)
        char_total += candidate_len
        consumed += 1

    if not lines:
        logger.info(
            "stt_enum_transcript_unavailable",
            extra={
                "video_id": video_id,
                "org_id": str(org_id),
                "hit_count": len(hits),
            },
        )
        raise TranscriptUnavailableError(
            f"video {video_id} has no scene with non-empty transcript_raw "
            f"(scanned {len(hits)} scene rows)"
        )

    if truncated:
        logger.info(
            "stt_enum_transcript_truncated",
            extra={
                "video_id": video_id,
                "org_id": str(org_id),
                "scenes_consumed": consumed,
                "scenes_total": len(hits),
                "char_cap": char_cap,
            },
        )

    return "\n".join(lines), consumed
