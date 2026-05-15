from pydantic import BaseModel


class FaceMatchRequest(BaseModel):
    org_id: str
    embeddings: list[list[float]]
    threshold: float = 0.55


class FaceMatchResult(BaseModel):
    cluster_id: str | None
    similarity: float | None


class FaceMatchResponse(BaseModel):
    matches: list[FaceMatchResult]


class FaceIdentityUpsert(BaseModel):
    cluster_id: str
    embedding: list[float]
    quality: float
    video_id: str
    scene_id: str
    is_new: bool
    bbox_json: dict[str, object] | None = None


class FaceIdentityUpsertRequest(BaseModel):
    org_id: str
    identities: list[FaceIdentityUpsert]


class ExemplarIdMapping(BaseModel):
    cluster_id: str
    exemplar_id: str


class FaceIdentityUpsertResponse(BaseModel):
    created: int
    updated: int
    exemplar_ids: list[ExemplarIdMapping] = []
