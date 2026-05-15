import unicodedata

from pydantic import BaseModel, Field, field_validator


class PersonResponse(BaseModel):
    person_cluster_id: str
    label: str | None = None
    face_count: int = 0
    last_seen_scene_time: str | None = None
    representative_video_id: str | None = None
    representative_scene_id: str | None = None
    thumbnail_source: str = "auto"
    is_excluded: bool = False
    matched_video_titles: list[str] | None = None


class PeopleListResponse(BaseModel):
    people: list[PersonResponse]
    total: int


class RenamePersonRequest(BaseModel):
    label: str | None = Field(None, max_length=100)

    @field_validator("label", mode="before")
    @classmethod
    def clean_label(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = unicodedata.normalize("NFC", v)
        v = "".join(c for c in v if not unicodedata.category(c).startswith("C"))
        v = v.strip()
        return v if v else None


class RenamePersonResponse(BaseModel):
    person_cluster_id: str
    label: str | None = None


class PersonVideoItem(BaseModel):
    video_id: str
    video_title: str | None = None
    scene_count: int = 0


class PersonVideosResponse(BaseModel):
    person_cluster_id: str
    videos: list[PersonVideoItem]
    total: int


class ExcludePreferencesResponse(BaseModel):
    excluded_person_cluster_ids: list[str]


class SetExcludePreferencesRequest(BaseModel):
    person_cluster_ids: list[str] = Field(default_factory=list, max_length=500)


class VideoExclusionsResponse(BaseModel):
    person_cluster_id: str
    excluded_video_ids: list[str]


class SetVideoExclusionsRequest(BaseModel):
    excluded_video_ids: list[str] = Field(default_factory=list, max_length=200)


class PersonTimelineScene(BaseModel):
    scene_id: str
    start_ms: int
    end_ms: int
    has_person: bool


class PersonTimelineVideo(BaseModel):
    video_id: str
    video_title: str | None = None
    total_scenes: int
    scenes: list[PersonTimelineScene]


class PersonTimelineResponse(BaseModel):
    person_cluster_id: str
    videos: list[PersonTimelineVideo]


class MergePersonRequest(BaseModel):
    """Request to merge one or more source clusters into a target cluster.

    The target cluster survives; source clusters are absorbed and deleted.
    Supports batch merge (multiple sources into one target).
    """

    source_cluster_ids: list[str] = Field(
        ..., min_length=1, max_length=50,
        description="Cluster IDs to be absorbed and deleted",
    )
    target_cluster_id: str = Field(
        ...,
        description="Cluster ID that survives the merge",
    )
    keep_label: str | None = Field(
        None, max_length=100,
        description="Override label for the merged cluster. If None, uses existing target label or inherits from source.",
    )

    @field_validator("keep_label", mode="before")
    @classmethod
    def clean_keep_label(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = unicodedata.normalize("NFC", v)
        v = "".join(c for c in v if not unicodedata.category(c).startswith("C"))
        v = v.strip()
        return v if v else None


class MergePersonResponse(BaseModel):
    """Result of a person cluster merge operation."""

    target_cluster_id: str
    merged_source_ids: list[str]
    scenes_updated: int
    label: str | None = None


class BulkDeleteRequest(BaseModel):
    """Request to bulk delete multiple person clusters."""

    person_cluster_ids: list[str] = Field(
        ..., min_length=1, max_length=50,
        description="Cluster IDs to delete (max 50)",
    )


class BulkDeleteResponse(BaseModel):
    """Result of a bulk delete operation."""

    deleted_ids: list[str]
    failed_ids: list[str]
    total_deleted: int


class SimilarPersonItem(BaseModel):
    person_cluster_id: str
    similarity: float


class SimilarPeopleResponse(BaseModel):
    target_cluster_id: str
    similarities: list[SimilarPersonItem]
    total: int
    threshold: float


class ExemplarResponse(BaseModel):
    exemplar_id: str
    video_id: str
    scene_id: str
    quality: float
    thumbnail_url: str


class ExemplarListResponse(BaseModel):
    exemplars: list[ExemplarResponse]
    total: int


class SetThumbnailRequest(BaseModel):
    exemplar_id: str


class ThumbnailResponse(BaseModel):
    person_cluster_id: str
    thumbnail_source: str


class LinkPersonVideoRequest(BaseModel):
    """Link or unlink a person from all scenes in a video."""

    video_id: str = Field(..., min_length=1)


class LinkPersonVideoResponse(BaseModel):
    """Response for link/unlink operations."""

    person_cluster_id: str
    video_id: str
    scenes_updated: int
