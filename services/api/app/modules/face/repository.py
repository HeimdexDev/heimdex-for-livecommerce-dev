from typing import TypedDict, cast
from uuid import UUID

import numpy as np
from sqlalchemy import select, text
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
        matches: list[FaceMatchRow | None] = []

        query = text(
            """
            SELECT cluster_id, 1 - (centroid_embedding <=> CAST(:embedding AS vector)) AS similarity
            FROM face_identities
            WHERE org_id = :org_id
            ORDER BY centroid_embedding <=> CAST(:embedding AS vector)
            LIMIT 1
            """
        )

        for embedding in embeddings:
            result = await self.session.execute(
                query,
                {"org_id": str(org_id), "embedding": str(embedding)},
            )
            row = result.mappings().first()
            if row is None:
                matches.append(None)
                continue

            similarity = float(row["similarity"])
            if similarity < threshold:
                matches.append(None)
                continue

            matches.append(
                {
                    "cluster_id": str(row["cluster_id"]),
                    "similarity": similarity,
                }
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


class FaceMatchRow(TypedDict):
    cluster_id: str
    similarity: float
