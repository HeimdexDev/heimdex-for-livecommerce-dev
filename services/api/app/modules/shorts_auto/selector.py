"""Mode-aware OpenSearch query for auto-shorts candidate scenes.

Owns its own OS query construction so the auto-shorts feature can evolve
its filters without affecting other consumers of the scene index. Reads
through the injected scene OpenSearch client (the same one used by the
shorts_render boundary validator); never touches the underlying class
state directly beyond ``client`` and ``alias_name``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from heimdex_media_contracts.scenes.schemas import SceneDocument
from heimdex_media_contracts.shorts.scorer import ScoringMode

logger = logging.getLogger(__name__)

# Scene fields the scorer + concatenator read. Keep in sync with
# ``heimdex_media_contracts.shorts.scorer.score_scene_for_mode``.
#
# ``speaker_transcript`` is NOT a typed field on contracts SceneDocument
# (would need a contracts version bump + cross-repo work). Pydantic
# drops it silently during SceneDocument(**src) parsing. We pull it out
# of the raw _source separately and surface it via CandidateScenesResult
# so downstream consumers (notably the auto-shorts script panel) can
# render it without re-querying.
_SOURCE_FIELDS: list[str] = [
    "scene_id",
    "video_id",
    "index",
    "start_ms",
    "end_ms",
    "keyframe_timestamp_ms",
    "transcript_raw",
    "transcript_norm",
    "transcript_char_count",
    "speech_segment_count",
    "people_cluster_ids",
    "keyword_tags",
    "product_tags",
    "product_entities",
    "scene_caption",
    "ocr_text_raw",
    "ocr_char_count",
    "speaker_transcript",
]


@dataclass(frozen=True)
class CandidateScenesResult:
    """Selector result — typed scenes plus app-side enrichments.

    ``scenes`` is the contracts-typed list passed to the scorer. The
    scorer signature is unchanged.

    ``speaker_transcripts`` maps ``scene_id`` to the raw
    ``speaker_transcript`` text from OpenSearch, when present. Empty
    strings are dropped from the map so callers can do truthiness checks.
    """

    scenes: list[SceneDocument]
    speaker_transcripts: dict[str, str] = field(default_factory=dict)

# Realistic upper bound for one video's scenes. The largest videos in
# staging today produce ~400 scenes; 1000 is a 2.5x headroom.
_MAX_SCENES_PER_VIDEO = 1000


class AutoShortsSelector:
    """Fetches candidate scenes for auto-shorts selection."""

    def __init__(self, scene_opensearch: Any) -> None:
        self.scene_opensearch = scene_opensearch

    async def fetch_candidates(
        self,
        org_id: UUID,
        video_id: str,
        mode: ScoringMode,
        person_cluster_id: str | None = None,
    ) -> CandidateScenesResult:
        """Return scenes that pass the cheap pre-filter for ``mode``.

        The scorer applies the authoritative hard filter again — the OS
        pre-filter is just a query optimization to avoid pulling scenes
        that obviously don't qualify. If the OS filter and the scorer
        ever diverge, the scorer wins (more conservative).

        Returns a :class:`CandidateScenesResult` carrying both the typed
        ``scenes`` list and a ``speaker_transcripts`` map. The latter is
        an app-side enrichment surfaced separately because contracts
        ``SceneDocument`` deliberately omits ``speaker_transcript``.
        """
        query_filter: list[dict[str, Any]] = [
            {"term": {"org_id": str(org_id)}},
            {"term": {"video_id": video_id}},
        ]
        must_not: list[dict[str, Any]] = []

        if mode == ScoringMode.HUMAN:
            if person_cluster_id:
                query_filter.append(
                    {"term": {"people_cluster_ids": person_cluster_id}}
                )

        elif mode == ScoringMode.PRODUCT:
            # OS-side pre-filter: scenes with at least one product signal.
            # The scorer rejects scenes with people_cluster_ids non-empty;
            # we mirror that here to drop them from the result set early.
            must_not.append(
                {
                    "script": {
                        "script": {
                            "source": (
                                "doc['people_cluster_ids'].size() > 0"
                            ),
                            "lang": "painless",
                        }
                    }
                }
            )
            query_filter.append(
                {
                    "bool": {
                        "should": [
                            {
                                "script": {
                                    "script": {
                                        "source": (
                                            "doc['product_tags'].size() > 0"
                                        ),
                                        "lang": "painless",
                                    }
                                }
                            },
                            {
                                "script": {
                                    "script": {
                                        "source": (
                                            "doc['product_entities'].size() > 0"
                                        ),
                                        "lang": "painless",
                                    }
                                }
                            },
                        ],
                        "minimum_should_match": 1,
                    }
                }
            )

        # BOTH mode applies no extra filters — let the scorer rank everything.

        body: dict[str, Any] = {
            "query": {
                "bool": {
                    "filter": query_filter,
                    "must_not": must_not,
                }
            },
            "_source": _SOURCE_FIELDS,
            "size": _MAX_SCENES_PER_VIDEO,
            "sort": [{"start_ms": "asc"}],
        }

        response = await self.scene_opensearch.client.search(
            index=self.scene_opensearch.alias_name,
            body=body,
        )
        hits = response.get("hits", {}).get("hits", [])

        out: list[SceneDocument] = []
        speaker_transcripts: dict[str, str] = {}
        for hit in hits:
            src = hit.get("_source") or {}
            # OpenSearch mapping doesn't store ``index`` separately — the
            # value is embedded in scene_id as the trailing ``_scene_NNN``
            # suffix (see drive-worker/src/tasks/process.py where ids are
            # built). SceneDocument.index is required, so derive it here
            # before handing to Pydantic. Any scene_id that doesn't match
            # the pattern is skipped + logged so one drift doesn't fail
            # the whole request.
            if "index" not in src:
                derived = _derive_index_from_scene_id(src.get("scene_id"))
                if derived is None:
                    logger.warning(
                        "auto_shorts_selector_scene_id_parse_failed",
                        extra={
                            "scene_id": src.get("scene_id"),
                            "video_id": video_id,
                        },
                    )
                    continue
                src = {**src, "index": derived}
            try:
                doc = SceneDocument(**src)
            except Exception:
                # Malformed scenes get logged and skipped — never fail the
                # whole request because one document drifted from schema.
                logger.warning(
                    "auto_shorts_selector_scene_parse_failed",
                    extra={"scene_id": src.get("scene_id"), "video_id": video_id},
                    exc_info=True,
                )
                continue
            out.append(doc)
            # Pluck the app-side enrichment that contracts doesn't carry.
            # Empty strings are skipped so callers can use ``in`` / truthy
            # checks without thinking about " " vs missing.
            speaker_text = src.get("speaker_transcript")
            if isinstance(speaker_text, str) and speaker_text.strip():
                speaker_transcripts[doc.scene_id] = speaker_text
        return CandidateScenesResult(
            scenes=out,
            speaker_transcripts=speaker_transcripts,
        )


def _derive_index_from_scene_id(scene_id: Any) -> int | None:
    """Extract the numeric index from a ``{video_id}_scene_NNN`` scene_id.

    Returns ``None`` when the input isn't a string or doesn't contain
    the expected suffix — caller skips such scenes.
    """
    if not isinstance(scene_id, str):
        return None
    marker = "_scene_"
    pos = scene_id.rfind(marker)
    if pos < 0:
        return None
    try:
        return int(scene_id[pos + len(marker):])
    except ValueError:
        return None
