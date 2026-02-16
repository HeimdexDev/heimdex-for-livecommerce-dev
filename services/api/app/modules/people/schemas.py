import unicodedata

from pydantic import BaseModel, Field, field_validator


class PersonResponse(BaseModel):
    person_cluster_id: str
    label: str | None = None
    face_count: int = 0
    last_seen_scene_time: str | None = None


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
