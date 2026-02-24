"""Heimdex Worker SDK — shared settings, S3 client, drive key helpers, and internal API client."""

from heimdex_worker_sdk.drive_keys import (
    audio_s3_key,
    drive_video_id,
    enrichment_keyframe_s3_key,
    enrichment_keyframe_s3_prefix,
    proxy_s3_key,
    scene_manifest_s3_key,
    thumbnail_s3_key,
    thumbnail_s3_prefix,
)
from heimdex_worker_sdk.s3 import S3Client
from heimdex_worker_sdk.settings import WorkerSettings, get_worker_settings
from heimdex_worker_sdk.internal_api import ClaimedFile, InternalAPIClient

__all__ = [
    "WorkerSettings",
    "get_worker_settings",
    "S3Client",
    "InternalAPIClient",
    "ClaimedFile",
    "audio_s3_key",
    "drive_video_id",
    "enrichment_keyframe_s3_key",
    "enrichment_keyframe_s3_prefix",
    "proxy_s3_key",
    "scene_manifest_s3_key",
    "thumbnail_s3_key",
    "thumbnail_s3_prefix",
]
