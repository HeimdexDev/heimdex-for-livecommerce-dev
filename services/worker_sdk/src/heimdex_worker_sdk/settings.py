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
    # When minio_endpoint is empty, the S3 client uses real AWS S3 with
    # IAM/env credentials instead of a MinIO-compatible endpoint.
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "heimdex"
    minio_secret_key: str = "heimdex_dev_password"
    minio_secure: bool = False
    s3_region: str = "ap-northeast-2"

    # --- Drive common ---
    drive_s3_bucket: str = "heimdex-drive"
    drive_internal_api_key: str = ""
    drive_api_base_url: str = "http://api:8000"
    drive_connector_enabled: bool = False
    drive_enrichment_enabled: bool = False
    folder_sync_v2_enabled: bool = False

    # --- Image processing ---
    image_processing_enabled: bool = False

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
    drive_transcode_mode: str = "cpu"  # "cpu" (drive-worker transcodes) or "gpu" (Aircloud+ transcode-worker)
    drive_download_chunk_size: int = 10 * 1024 * 1024
    drive_download_max_retries: int = 3

    # --- Caption enrichment ---
    scene_caption_enabled: bool = False
    drive_caption_concurrency: int = 1
    drive_caption_model: str = "Qwen/Qwen2-VL-2B-Instruct"
    caption_engine: str = "qwen2vl"  # "qwen2vl", "internvl2", "florence2", or "llama_http"
    llama_caption_url: str = "http://llama-caption-server:8089"
    llama_caption_api_key: str = ""

    # --- STT enrichment ---
    drive_stt_enabled: bool = False
    drive_stt_model: str = "turbo"
    drive_stt_language: str = "ko"
    drive_stt_backend: str = "faster-whisper"
    drive_stt_concurrency: int = 1
    drive_stt_max_audio_seconds: int = 21600  # 6 hours; faster-whisper handles long audio natively

    # --- Speaker diarization (pyannote.audio, runs inside STT worker) ---
    drive_stt_diarization_enabled: bool = False
    drive_stt_diarization_model: str = "pyannote/speaker-diarization-3.1"
    drive_stt_min_speakers: int = 1
    drive_stt_max_speakers: int = 4
    hf_access_token: str = ""

    # --- OCR enrichment ---
    drive_ocr_enabled: bool = False
    drive_ocr_concurrency: int = 1
    drive_ocr_max_frames_per_scene: int = 10
    drive_ocr_max_frames_per_video: int = 300


    # --- SQS (Phase 3 complete — enrichment workers are mandatory SQS consumers) ---
    sqs_enabled: bool = False
    sqs_consumer_enabled: bool = False
    sqs_endpoint_url: str = ""
    sqs_region: str = "ap-northeast-2"
    sqs_processing_queue_url: str = ""
    sqs_caption_queue_url: str = ""
    sqs_stt_queue_url: str = ""
    sqs_ocr_queue_url: str = ""
    sqs_transcode_queue_url: str = ""
    sqs_face_queue_url: str = ""
    sqs_visual_embed_queue_url: str = ""
    sqs_export_queue_url: str = ""

    # --- Proxy-pack export ---
    export_max_size_bytes: int = 2_147_483_648
    export_max_clips: int = 100
    export_max_proxies: int = 20
    export_expiry_days: int = 3


    # --- Aircloud GPU worker orchestration ---
    aircloud_enabled: bool = False
    aircloud_api_key: str = ""
    aircloud_endpoint_transcode: str = ""
    aircloud_endpoint_caption: str = ""
    aircloud_endpoint_stt: str = ""
    aircloud_endpoint_ocr: str = ""
    aircloud_endpoint_face: str = ""
    aircloud_endpoint_visual_embed: str = ""
    aircloud_wake_debounce_seconds: int = 300
    aircloud_cooldown_checks: int = 3

    # --- GPU acceleration (AirCloud+ remote workers) ---
    use_gpu: bool = False  # Set True on GPU instances; caption/OCR engines auto-detect CUDA
    stt_device: str = "cpu"  # "cpu", "cuda", or "auto"; faster-whisper device selection
    stt_compute_type: str = "int8"  # "int8", "float16", "float32", "auto"; GPU prefers float16

    # --- Face detection ---
    face_match_threshold: float = 0.55
    drive_face_concurrency: int = 1

    # --- Visual embedding worker ---
    visual_embed_enabled: bool = False
    visual_embed_concurrency: int = 1
    class Config:
        env_file: str = ".env"
        env_file_encoding: str = "utf-8"


@lru_cache
def get_worker_settings() -> WorkerSettings:
    """Cached singleton — identical caching strategy to ``app.config.get_settings``."""
    return WorkerSettings()
