import json
from typing import TypedDict, cast
from uuid import UUID

import numpy as np
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.face.models import FaceExemplar, FaceIdentity

class FaceMatchRow(TypedDict):
    cluster_id: str
    similarity: float

class FaceRepository:
    def __init__(self, session: AsyncSession):
        self.session: AsyncSession = session

    async def match_embeddings(
        self, org_id: UUID, embeddings: list[list[float]], threshold: float
    ) -> list["FaceMatchRow | None"]:
        if not embeddings:
            return []

        result = await self.session.execute(
            text(
                "SELECT cluster_id, centroid_embedding "
                "FROM face_identities WHERE org_id = :org_id"
            ),
            {"org_id": str(org_id)},
        )
        rows = result.mappings().all()

        if not rows:
            return [None] * len(embeddings)

        cluster_ids = [str(r["cluster_id"]) for r in rows]

        def _parse_embedding(raw: object) -> list[float]:
            """Parse pgvector embedding from asyncpg (returns str) or ORM (returns ndarray/list)."""
            if isinstance(raw, str):
                return json.loads(raw)
            if isinstance(raw, np.ndarray):
                return raw.tolist()
            if isinstance(raw, (list, tuple)):
                return [float(x) for x in raw]
            raise TypeError(f"Unexpected embedding type: {type(raw)}")

        centroids = np.array([_parse_embedding(r["centroid_embedding"]) for r in rows], dtype=np.float32)

        input_arr = np.array(embeddings, dtype=np.float32)

        c_norms = np.linalg.norm(centroids, axis=1, keepdims=True)
        i_norms = np.linalg.norm(input_arr, axis=1, keepdims=True)
        c_norms = np.where(c_norms > 0, c_norms, 1.0)
        i_norms = np.where(i_norms > 0, i_norms, 1.0)

        similarity_matrix = (input_arr / i_norms) @ (centroids / c_norms).T

        matches: list[FaceMatchRow | None] = []
        for i in range(len(embeddings)):
            best_j = int(np.argmax(similarity_matrix[i]))
            best_sim = float(similarity_matrix[i, best_j])

            if best_sim < threshold:
                matches.append(None)
            else:
                matches.append(
                    {"cluster_id": cluster_ids[best_j], "similarity": best_sim}
                )

        return matches

    async def upsert_identity(
        self,
        org_id: UUID,
        cluster_id: str,
        embedding: list[float],
        quality: float,
        best_thumbnail_video_id: str | None,
    ) -> tuple[bool, UUID]:
        result = await self.session.execute(
            select(FaceIdentity).where(
                FaceIdentity.org_id == org_id,
                FaceIdentity.cluster_id == cluster_id,
            )
        )
        existing = result.scalar_one_or_none()

        new_embedding = np.array(embedding, dtype=np.float32)
        norm = float(np.linalg.norm(new_embedding))
        if norm > 0.0:
            new_embedding = new_embedding / norm

        if existing is not None:
            old_centroid = np.array(existing.centroid_embedding, dtype=np.float32)
            old_count = float(existing.exemplar_count)
            weight = max(float(quality), 0.0)
            denominator = old_count + weight

            if denominator > 0.0:
                centroid = (old_centroid * old_count + new_embedding * weight) / denominator
            else:
                centroid = new_embedding

            centroid_norm = float(np.linalg.norm(centroid))
            if centroid_norm > 0.0:
                centroid = centroid / centroid_norm

            existing.centroid_embedding = centroid.tolist()
            existing.exemplar_count += 1

            if quality > existing.best_quality:
                existing.best_quality = quality
                existing.best_thumbnail_video_id = best_thumbnail_video_id

            await self.session.flush()
            return (False, cast(UUID, existing.id))

        entry = FaceIdentity(
            org_id=org_id,
            cluster_id=cluster_id,
            centroid_embedding=new_embedding.tolist(),
            exemplar_count=1,
            best_quality=quality,
            best_thumbnail_video_id=best_thumbnail_video_id,
        )
        self.session.add(entry)
        await self.session.flush()
        return (True, cast(UUID, entry.id))

    async def get_exemplars_for_identity(
        self, org_id: UUID, cluster_id: str, limit: int = 20,
    ) -> list[FaceExemplar]:
        result = await self.session.execute(
            select(FaceExemplar)
            .join(FaceIdentity, FaceExemplar.identity_id == FaceIdentity.id)
            .where(FaceIdentity.org_id == org_id, FaceIdentity.cluster_id == cluster_id)
            .order_by(FaceExemplar.quality.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_thumbnail_source(self, org_id: UUID, cluster_id: str) -> str | None:
        result = await self.session.execute(
            select(FaceIdentity.thumbnail_source).where(
                FaceIdentity.org_id == org_id,
                FaceIdentity.cluster_id == cluster_id,
            )
        )
        return result.scalar_one_or_none()

    async def set_thumbnail_source(
        self, org_id: UUID, cluster_id: str, source: str, exemplar_id: UUID | None = None,
    ) -> FaceIdentity | None:
        result = await self.session.execute(
            select(FaceIdentity).where(
                FaceIdentity.org_id == org_id,
                FaceIdentity.cluster_id == cluster_id,
            )
        )
        identity = result.scalar_one_or_none()
        if identity is None:
            return None
        identity.thumbnail_source = source
        identity.selected_exemplar_id = exemplar_id
        await self.session.flush()
        return identity

    async def reset_thumbnail_source(self, org_id: UUID, cluster_id: str) -> FaceIdentity | None:
        return await self.set_thumbnail_source(org_id, cluster_id, "auto", None)

    async def get_exemplar_by_id(
        self, org_id: UUID, exemplar_id: UUID,
    ) -> FaceExemplar | None:
        result = await self.session.execute(
            select(FaceExemplar).where(
                FaceExemplar.org_id == org_id,
                FaceExemplar.id == exemplar_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_thumbnail_sources_batch(
        self, org_id: UUID, cluster_ids: list[str],
    ) -> dict[str, str]:
        if not cluster_ids:
            return {}
        result = await self.session.execute(
            select(FaceIdentity.cluster_id, FaceIdentity.thumbnail_source).where(
                FaceIdentity.org_id == org_id,
                FaceIdentity.cluster_id.in_(cluster_ids),
            )
        )
        return {row.cluster_id: row.thumbnail_source for row in result.all()}

    async def get_exemplar_ids_for_identity(
        self, org_id: UUID, cluster_id: str,
    ) -> list[UUID]:
        result = await self.session.execute(
            select(FaceExemplar.id)
            .join(FaceIdentity, FaceExemplar.identity_id == FaceIdentity.id)
            .where(FaceIdentity.org_id == org_id, FaceIdentity.cluster_id == cluster_id)
        )
        return list(result.scalars().all())

    async def add_exemplar(
        self,
        identity_id: UUID,
        org_id: UUID,
        video_id: str,
        scene_id: str,
        embedding: list[float],
        quality: float,
        bbox_json: dict[str, object] | None,
    ) -> None:
        exemplar = FaceExemplar(
            identity_id=identity_id,
            org_id=org_id,
            video_id=video_id,
            scene_id=scene_id,
            embedding=embedding,
            quality=quality,
            bbox_json=bbox_json,
        )
        self.session.add(exemplar)
        await self.session.flush()

    async def merge_identities(
        self,
        org_id: UUID,
        source_cluster_id: str,
        target_cluster_id: str,
    ) -> bool:
        """Merge source face identity into target.

        Steps:
        1. Reassign all source exemplars to target identity
        2. Recompute target centroid as weighted average of both centroids
        3. Update target exemplar_count and best_quality
        4. Delete source identity row

        Returns True if merge happened, False if source identity not found.
        """
        # Fetch both identities
        source_result = await self.session.execute(
            select(FaceIdentity).where(
                FaceIdentity.org_id == org_id,
                FaceIdentity.cluster_id == source_cluster_id,
            )
        )
        source = source_result.scalar_one_or_none()
        if source is None:
            return False

        target_result = await self.session.execute(
            select(FaceIdentity).where(
                FaceIdentity.org_id == org_id,
                FaceIdentity.cluster_id == target_cluster_id,
            )
        )
        target = target_result.scalar_one_or_none()

        if target is not None:
            # Recompute target centroid as weighted average
            src_centroid = np.array(source.centroid_embedding, dtype=np.float32)
            tgt_centroid = np.array(target.centroid_embedding, dtype=np.float32)
            src_weight = float(source.exemplar_count)
            tgt_weight = float(target.exemplar_count)
            total_weight = src_weight + tgt_weight

            if total_weight > 0.0:
                merged_centroid = (tgt_centroid * tgt_weight + src_centroid * src_weight) / total_weight
            else:
                merged_centroid = tgt_centroid

            centroid_norm = float(np.linalg.norm(merged_centroid))
            if centroid_norm > 0.0:
                merged_centroid = merged_centroid / centroid_norm

            target.centroid_embedding = merged_centroid.tolist()
            target.exemplar_count += source.exemplar_count

            if source.best_quality > target.best_quality:
                target.best_quality = source.best_quality
                target.best_thumbnail_video_id = source.best_thumbnail_video_id

            # Preserve user-selected thumbnail: if target is auto and source is not, inherit
            if target.thumbnail_source == "auto" and source.thumbnail_source != "auto":
                target.thumbnail_source = source.thumbnail_source
                target.selected_exemplar_id = source.selected_exemplar_id

            # Reassign all source exemplars to target identity
            await self.session.execute(
                update(FaceExemplar)
                .where(FaceExemplar.identity_id == source.id)
                .values(identity_id=target.id)
            )
        else:
            # Target has no face identity — just rename the source
            source.cluster_id = target_cluster_id
            await self.session.flush()
            return True

        # Delete source identity
        await self.session.delete(source)
        await self.session.flush()
        return True
