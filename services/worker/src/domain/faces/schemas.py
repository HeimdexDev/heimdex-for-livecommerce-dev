from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

class Interval(BaseModel):
    start_s: float
    end_s: float
    confidence: float

class SceneSummary(BaseModel):
    scene_id: str
    present: Optional[bool]  # true / false / unknown
    confidence: float

class IdentityPresence(BaseModel):
    identity_id: str
    intervals: List[Interval]
    scene_summary: List[SceneSummary]

class FacePresenceResponse(BaseModel):
    video_id: str
    identities: List[IdentityPresence]
    meta: dict
