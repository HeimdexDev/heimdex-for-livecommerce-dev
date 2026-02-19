"""
Scene ingestion service.

Orchestrates the full ingest pipeline:
1. Validate library_id belongs to the resolved org
2. Normalize transcript_raw → transcript_norm (SaaS-side)
3. Generate E5 embedding for non-empty transcripts (SaaS-side)
4. Stamp org_id, ingest_time, compute transcript_char_count
5. Build composite doc_id = "{org_id}:{scene_id}"
6. Bulk index into the scenes OpenSearch index

Design decisions (from Oracle review):
- Embedding happens SaaS-side (centralizes E5 model; agent sends text only)
- Empty transcripts: index scene metadata but OMIT embedding_vector entirely
  (kNN search implicitly filters scenes without embedding)
- Doc ID "{org_id}:{scene_id}" prevents cross-tenant overwrites
- SaaS applies its own normalize_transcript() on the raw text
"""
import time as _time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.logging_config import get_logger
from app.modules.ingest.schemas import IngestSceneDocument, IngestScenesRequest
from app.modules.libraries.repository import LibraryRepository
from app.modules.search.embedding import get_passage_embedding, get_passage_embeddings_batch
from app.modules.search.normalize import normalize_transcript
from app.modules.search.scene_client import SceneSearchClient

logger = get_logger(__name__)


class SceneIngestService:
    """Shared scene ingest pipeline for all sources (agent, Drive, etc.).

    Normalizes transcripts, generates E5 embeddings, and bulk-indexes
    into the scenes OpenSearch index.  Source-specific logic (download,
    transcode, scene detection) happens upstream — this service receives
    finished scene data regardless of origin.
    """

    def __init__(
        self,
        session: AsyncSession,
        scene_opensearch: SceneSearchClient,
    ) -> None:
        self.session = session
        self.scene_opensearch = scene_opensearch

    async def ingest_scenes(
        self,
        request: IngestScenesRequest,
        org_id: UUID,
    ) -> dict[str, Any]:
        """
        Ingest scene documents from the agent into the scenes index.

        Args:
            request: Validated ingest request with video_id, library_id, scenes.
            org_id: Organization ID resolved from Host header.

        Returns:
            Dict with indexed_count, video_id, skipped_count.

        Raises:
            ValueError: If library_id does not belong to the org.
        """
        t_start = _time.monotonic()

        logger.info(
            "scene_ingest_started",
            org_id=str(org_id),
            video_id=request.video_id,
            library_id=str(request.library_id),
            scene_count=len(request.scenes),
        )

        # 1. Validate library ownership
        library_repo = LibraryRepository(self.session)
        library = await library_repo.get_by_id(request.library_id, org_id)
        if library is None:
            raise ValueError(
                f"Library {request.library_id} not found or does not belong to org {org_id}"
            )

        t_after_validation = _time.monotonic()

        # 2. Normalize transcripts once and cache results
        now = datetime.now(timezone.utc)
        org_id_str = str(org_id)

        normalized: list[tuple[str, str, int]] = []
        for scene in request.scenes:
            transcript_norm = normalize_transcript(scene.transcript_raw)
            ocr_norm = normalize_transcript(scene.ocr_text_raw) if scene.ocr_text_raw else ""
            ocr_char_count = len(ocr_norm)
            normalized.append((transcript_norm, ocr_norm, ocr_char_count))

        transcripts_to_embed: list[tuple[int, str]] = []
        for idx, (transcript_norm, ocr_norm, _) in enumerate(normalized):
            embedding_text = transcript_norm
            if ocr_norm:
                embedding_text = (
                    f"{transcript_norm} {ocr_norm}".strip() if transcript_norm else ocr_norm
                )
            if embedding_text:
                transcripts_to_embed.append((idx, embedding_text))

        # 3. Batch embed non-empty transcripts
        embeddings: dict[int, list[float]] = {}
        if transcripts_to_embed:
            texts = [t for _, t in transcripts_to_embed]
            vectors = get_passage_embeddings_batch(texts)
            for (idx, _), vec in zip(transcripts_to_embed, vectors):
                embeddings[idx] = vec

        t_after_embedding = _time.monotonic()

        # 4. Build bulk index payload (reuse cached normalized transcripts)
        documents: list[tuple[str, dict[str, Any]]] = []
        for idx, scene in enumerate(request.scenes):
            transcript_norm, ocr_norm, ocr_char_count = normalized[idx]
            char_count = len(transcript_norm)

            doc: dict[str, Any] = {
                "org_id": org_id_str,
                "library_id": str(request.library_id),
                "video_id": request.video_id,
                "video_title": request.video_title,
                "scene_id": scene.scene_id,
                "start_ms": scene.start_ms,
                "end_ms": scene.end_ms,
                "transcript_raw": scene.transcript_raw,
                "transcript_norm": transcript_norm,
                "transcript_char_count": char_count,
                "speech_segment_count": scene.speech_segment_count,
                "people_cluster_ids": scene.people_cluster_ids,
                "keyword_tags": scene.keyword_tags,
                "product_tags": scene.product_tags,
                "product_entities": scene.product_entities,
                "ocr_text_raw": scene.ocr_text_raw,
                "ocr_text_norm": ocr_norm,
                "ocr_char_count": ocr_char_count,
                "source_type": scene.source_type,
                "required_drive_nickname": scene.required_drive_nickname,
                "capture_time": scene.capture_time.isoformat() if scene.capture_time else None,
                "ingest_time": now.isoformat(),
                "keyframe_timestamp_ms": scene.keyframe_timestamp_ms,
                "source_path": request.source_path,
            }

            # Only add embedding if transcript is non-empty
            if idx in embeddings:
                doc["embedding_vector"] = embeddings[idx]

            # Composite doc_id: "{org_id}:{scene_id}"
            doc_id = f"{org_id_str}:{scene.scene_id}"
            documents.append((doc_id, doc))

        # 5. Bulk index
        await self.scene_opensearch.bulk_index_scenes(documents)

        all_cluster_ids: set[str] = set()
        for scene in request.scenes:
            for cluster_id in scene.people_cluster_ids:
                if cluster_id:
                    all_cluster_ids.add(cluster_id)

        if all_cluster_ids:
            try:
                from app.modules.people.repository import PeopleClusterLabelRepository

                people_repo = PeopleClusterLabelRepository(self.session)
                for cluster_id in all_cluster_ids:
                    existing = await people_repo.get_by_cluster_id(org_id, cluster_id)
                    if existing is None:
                        await people_repo.set_label(org_id, cluster_id, None)
                await self.session.flush()
                logger.info(
                    "people_cluster_labels_upserted",
                    org_id=org_id_str,
                    video_id=request.video_id,
                    cluster_count=len(all_cluster_ids),
                )
            except Exception as e:
                logger.warning(
                    "people_cluster_labels_upsert_failed",
                    org_id=org_id_str,
                    video_id=request.video_id,
                    error=str(e),
                )

        t_after_index = _time.monotonic()

        logger.info(
            "scene_ingest_completed",
            org_id=org_id_str,
            video_id=request.video_id,
            indexed_count=len(documents),
            duration_validation_ms=round((t_after_validation - t_start) * 1000, 1),
            duration_embedding_ms=round((t_after_embedding - t_after_validation) * 1000, 1),
            duration_indexing_ms=round((t_after_index - t_after_embedding) * 1000, 1),
            duration_total_ms=round((t_after_index - t_start) * 1000, 1),
        )

        return {
            "indexed_count": len(documents),
            "video_id": request.video_id,
            "skipped_count": 0,
        }
