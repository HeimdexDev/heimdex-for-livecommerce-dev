import hashlib


def drive_video_id(org_id: str, google_file_id: str) -> str:
    """Deterministic video_id for Drive files. Collision-resistant, idempotent."""
    digest = hashlib.sha256(f"{org_id}:{google_file_id}".encode()).hexdigest()[:16]
    return f"gd_{digest}"


def proxy_s3_key(org_id: str, drive_id: str, google_file_id: str) -> str:
    return f"{org_id}/drive/{drive_id}/{google_file_id}/proxy.mp4"


def thumbnail_s3_key(org_id: str, video_id: str, scene_id: str) -> str:
    return f"{org_id}/drive/thumbs/{video_id}/{scene_id}.jpg"


def thumbnail_s3_prefix(org_id: str, video_id: str) -> str:
    return f"{org_id}/drive/thumbs/{video_id}/"
