"""Drive S3 key helpers — standalone copy of ``app.modules.drive.keys``.

Pure functions, only ``hashlib`` dependency.  Kept 1:1 with the API copy so
that workers and the API always generate identical keys.
"""

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


def audio_s3_key(org_id: str, video_id: str) -> str:
    return f"{org_id}/drive/audio/{video_id}/audio.wav"


def enrichment_keyframe_s3_prefix(org_id: str, video_id: str) -> str:
    return f"{org_id}/drive/keyframes/{video_id}/"


def enrichment_keyframe_s3_key(
    org_id: str, video_id: str, scene_id: str,
) -> str:
    return f"{org_id}/drive/keyframes/{video_id}/{scene_id}.jpg"


def scene_manifest_s3_key(org_id: str, video_id: str) -> str:
    return f"{org_id}/drive/manifests/{video_id}/scenes.json"


def original_s3_key(org_id: str, drive_id: str, google_file_id: str) -> str:
    """S3 key for the original (pre-transcode) file uploaded by drive-worker."""
    return f"{org_id}/drive/{drive_id}/{google_file_id}/original"


def stt_result_s3_key(org_id: str, video_id: str) -> str:
    """S3 key for STT result JSON used by speech-aware scene splitting."""
    return f"{org_id}/drive/stt/{video_id}/stt_result.json"