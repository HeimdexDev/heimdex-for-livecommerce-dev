"""Worker-scoped settings.

Field names match ``app.config.Settings`` exactly so the same environment
variables work without any docker-compose or .env changes.  Only the fields
that workers actually need are declared here.

Post-Phase 1: workers are fully DB-free and communicate via internal HTTP
API only.  No database_url or ORM fields belong here.
"""

from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class WorkerSettings(BaseSettings):
    """Subset of Heimdex settings used by drive workers."""

    # --- Core ---
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"

    # --- MinIO / S3 ---
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "heimdex"
    minio_secret_key: str = "heimdex_dev_password"
    minio_secure: bool = False

    # --- Drive common ---
    drive_s3_bucket: str = "heimdex-drive"
    drive_internal_api_key: str = ""
    drive_api_base_url: str = "http://api:8000"
    drive_connector_enabled: bool = False
    drive_enrichment_enabled: bool = False

    # --- Drive worker ---
    drive_worker_poll_interval_seconds: int = 30
    drive_worker_global_concurrency: int = 2
    drive_worker_per_org_concurrency: int = 1
    drive_temp_disk_budget_gb: float = 50.0
    drive_temp_dir: str = "/data/drive-tmp"
    drive_proxy_max_height: int = 720
    drive_proxy_crf: int = 23
    drive_proxy_preset: str = "fast"
    drive_proxy_audio_bitrate: str = "128k"
    drive_proxy_max_bitrate: str = "2500k"
    drive_proxy_bufsize: str = "5000k"
    drive_download_chunk_size: int = 10 * 1024 * 1024
    drive_download_max_retries: int = 3

    # --- Caption enrichment ---
    scene_caption_enabled: bool = False
    drive_caption_poll_interval_seconds: int = 30  # DEPRECATED (Phase 3): enrichment workers use SQS only
    drive_caption_concurrency: int = 1
    drive_caption_model: str = "OpenGVLab/InternVL2-1B"
    caption_engine: str = "internvl2"
    llama_caption_url: str = "http://llama-caption-server:8089"
    llama_caption_api_key: str = ""

    # --- STT enrichment ---
    drive_stt_enabled: bool = False
    drive_stt_model: str = "small"
    drive_stt_language: str = "ko"
    drive_stt_backend: str = "faster-whisper"
    drive_stt_poll_interval_seconds: int = 30  # DEPRECATED (Phase 3): enrichment workers use SQS only
    drive_stt_concurrency: int = 1
    drive_stt_max_audio_seconds: int = 3600

    # --- OCR enrichment ---
    drive_ocr_enabled: bool = False
    drive_ocr_poll_interval_seconds: int = 30  # DEPRECATED (Phase 3): enrichment workers use SQS only
    drive_ocr_concurrency: int = 1
    drive_ocr_max_frames_per_scene: int = 10
    drive_ocr_max_frames_per_video: int = 300


    # --- SQS (Phase 0 producer / Phase 2 consumer / Phase 3 mandatory for enrichment) ---
    sqs_enabled: bool = False
    sqs_consumer_enabled: bool = False
    sqs_endpoint_url: str = ""
    sqs_region: str = "ap-northeast-2"
    sqs_processing_queue_url: str = ""
    sqs_caption_queue_url: str = ""
    sqs_stt_queue_url: str = ""
    sqs_ocr_queue_url: str = ""

    class Config:
        env_file: str = ".env"
        env_file_encoding: str = "utf-8"


@lru_cache
def get_worker_settings() -> WorkerSettings:
    """Cached singleton — identical caching strategy to ``app.config.get_settings``."""
    return WorkerSettings()
