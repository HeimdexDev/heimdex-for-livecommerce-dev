import logging
from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings

# Known insecure dev defaults that must never be used in production/staging.
_INSECURE_DEFAULTS = frozenset(
    {
        "dev-secret-key-change-in-production",
        "dev-agent-key-change-in-production",
        "dev-device-pepper-change-in-production",
    }
)


class ProductionGuardError(SystemExit):
    """Raised when production/staging starts with insecure dev defaults."""


class Settings(BaseSettings):
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    
    database_url: str = "postgresql+asyncpg://heimdex:heimdex_dev_password@localhost:5432/heimdex"
    database_url_sync: str = "postgresql://heimdex:heimdex_dev_password@localhost:5432/heimdex"

    # Database connection pool
    db_pool_size: int = 10
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800  # seconds; recycle connections after 30 minutes
    
    opensearch_url: str = "http://localhost:9200"
    opensearch_index_prefix: str = "heimdex"
    
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "heimdex"
    minio_secret_key: str = "heimdex_dev_password"
    minio_secure: bool = False
    s3_region: str = "ap-northeast-2"  # Used in AWS S3 mode (when minio_endpoint is empty)
    
    jwt_secret_key: str = "dev-secret-key-change-in-production"
    jwt_algorithm: str = "HS256"
    jwt_expiration_hours: int = 24
    
    allowed_hosts: str = "*.app.heimdex.local,localhost"
    
    auth0_enabled: bool = False
    auth0_domain: str = ""
    auth0_audience: str = ""
    auth0_algorithms: str = "RS256"
    auth0_org_claim: str = "https://heimdex.io/org_id"
    
    # Embedding model configuration
    embedding_model: str = "intfloat/multilingual-e5-large"
    embedding_dimension: int = 1024  # multilingual-e5-large uses 1024 dimensions
    embedding_device: str = "cpu"  # "cpu", "cuda", or "mps" for Apple Silicon
    embedding_use_mock: bool = False  # Set to True to use mock embeddings for testing

    # Visual embedding (SigLIP2) configuration
    visual_embedding_enabled: bool = False  # Enable SigLIP2 visual search at query time
    visual_embedding_model: str = "google/siglip2-base-patch16-256"
    visual_embedding_dimension: int = 768
    
    search_lexical_top_k: int = 200
    search_vector_top_k: int = 200
    search_rrf_k: int = 20
    search_max_scenes_per_video: int = 4
    search_page_size: int = 20
    ocr_search_enabled: bool = True
    ocr_bm25_boost: float = 0.6
    opensearch_facet_size: int = 100

    
    # OpenSearch bulk refresh policy: "true" (default, sync), "false" (async), or "wait_for".
    # Set OPENSEARCH_BULK_REFRESH="false" for higher ingest throughput at the cost of search latency.
    opensearch_bulk_refresh: str = "true"
    
    # Search mode: "segments" (default, backward-compatible) or "scenes"
    # Controls which index POST /api/search queries.
    # Rollback: flip back to "segments" — no code revert needed.
    search_default_mode: Literal["segments", "scenes"] = "segments"
    
    # Agent ingestion settings
    # Controls whether the agent scene ingest endpoint is active.
    agent_ingest_enabled: bool = True
    # Pre-shared API key for agent → SaaS authentication.
    # Must match the HEIMDEX_CLOUD_TOKEN configured on the agent.
    agent_api_key: str = "dev-agent-key-change-in-production"
    agent_api_key_mode: str = "global"  # "global", "per-org", or "per-device"
    # Maximum number of scenes per ingest request (DoS protection).
    agent_ingest_max_scenes: int = 500
    # Maximum characters allowed in transcript_raw per scene (OOM protection).
    agent_ingest_max_transcript_chars: int = 50_000
    thumbnail_storage_dir: str = "/data/thumbnails"

    # --- Device registration ---
    device_secret_pepper: str = "dev-device-pepper-change-in-production"
    pairing_code_ttl_minutes: int = 10

    # --- Agent intents ---
    agent_intents_enabled: bool = False
    agent_intent_ttl_minutes: int = 10
    agent_intent_max_per_org: int = 10
    agent_intent_exchange_max_attempts: int = 5

    people_enabled: bool = True
    face_match_threshold: float = 0.55

    # --- Google Drive connector ---
    drive_connector_enabled: bool = False
    drive_sa_encryption_key: str = ""  # AES-256 key (hex) for encrypting SA keys in drive_secrets
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
    drive_s3_bucket: str = "heimdex-drive"
    drive_internal_api_key: str = ""  # Pre-shared key for drive-worker → API internal ingest
    drive_api_base_url: str = "http://api:8000"  # API base URL for drive-worker HTTP calls
    drive_enrichment_enabled: bool = False

    # --- Google Drive OAuth (folder-scoped sync) ---
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_oauth_redirect_uri: str = ""  # e.g., https://devorg.app.heimdexdemo.dev/api/drive/oauth/callback

    # --- OCR enrichment worker ---
    drive_ocr_enabled: bool = False
    drive_ocr_concurrency: int = 1
    drive_ocr_max_frames_per_scene: int = 10
    drive_ocr_max_frames_per_video: int = 300

    # --- STT enrichment worker ---
    drive_stt_enabled: bool = False
    drive_stt_model: str = "turbo"
    drive_stt_language: str = "ko"
    drive_stt_backend: str = "faster-whisper"
    drive_stt_concurrency: int = 1
    drive_stt_max_audio_seconds: int = 21600

    # --- Caption enrichment worker ---
    scene_caption_enabled: bool = False
    drive_caption_concurrency: int = 1
    drive_caption_model: str = "Qwen/Qwen2-VL-2B-Instruct"
    caption_engine: str = "qwen2vl"  # "qwen2vl", "internvl2", "florence2", or "llama_http"



    # --- YouTube reference ---
    youtube_enabled: bool = False
    youtube_reference_library_name: str = "유튜브 레퍼런스"
    youtube_s3_bucket: str = ""  # Defaults to drive_s3_bucket if empty
    youtube_sync_interval_seconds: int = 21600  # 6 hours
    youtube_download_format: str = "bestvideo[height<=720][ext=mp4]+bestaudio[ext=m4a]/best[height<=720]"
    youtube_rate_limit_sleep: int = 3  # seconds between downloads
    youtube_rate_limit_max_sleep: int = 8
    youtube_max_concurrent_downloads: int = 2
    youtube_auto_delete_originals: bool = True
    youtube_original_ttl_days: int = 7  # S3 lifecycle fallback

    # --- SQS (Phase 3 complete — enrichment workers are mandatory SQS consumers) ---
    sqs_enabled: bool = False
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

    # --- Search analytics ---
    analytics_enabled: bool = True  # Record search events to Postgres
    analytics_export_enabled: bool = False  # Nightly S3 Parquet export
    analytics_s3_bucket: str = ""  # Defaults to drive_s3_bucket if empty
    analytics_s3_prefix: str = "analytics"

    # --- Proxy-pack export ---
    export_max_size_bytes: int = 2_147_483_648  # 2 GB
    export_max_clips: int = 100
    export_max_proxies: int = 20
    export_expiry_days: int = 3

    # --- CORS ---
    cors_allow_origin_regex: str = (
        r"^https?://"
        r"([a-z0-9][a-z0-9-]{0,}[a-z0-9]\.app\.(?:heimdex\.(?:co|local)|heimdexdemo\.dev)"
        r"|localhost"
        r"|127\.0\.0\.1)"
        r"(:\d+)?$"
    )
    cors_extra_origins: str = ""

    # --- Cookie safety (prep for future cookie-based auth) ---
    auth_cookie_secure: bool = True
    auth_cookie_samesite: str = "lax"
    auth_cookie_domain: str = ""

    # --- Replay protection ---
    ingest_require_timestamp: bool = False
    ingest_timestamp_skew_seconds: int = 300
    ingest_require_idempotency: bool = False
    ingest_idempotency_ttl_seconds: int = 600

    # --- Dev token refresh ---
    enable_dev_refresh: bool = True

    class Config:
        env_file: str = ".env"
        env_file_encoding: str = "utf-8"

    def validate_production_guards(self) -> None:
        if self.environment == "development":
            return

        errors: list[str] = []

        if self.jwt_secret_key in _INSECURE_DEFAULTS:
            errors.append(
                "JWT_SECRET_KEY is using the insecure dev default. "
                + "Set a strong random value: JWT_SECRET_KEY=$(openssl rand -hex 32)"
            )

        if self.agent_api_key in _INSECURE_DEFAULTS:
            errors.append(
                "AGENT_API_KEY is using the insecure dev default. "
                + "Set a strong random value: AGENT_API_KEY=$(openssl rand -hex 32)"
            )

        if not self.auth0_enabled:
            errors.append(
                "AUTH0_ENABLED is false. "
                + "Production requires Auth0 (or equivalent OIDC provider): AUTH0_ENABLED=true"
            )

        if self.device_secret_pepper in _INSECURE_DEFAULTS:
            errors.append(
                "DEVICE_SECRET_PEPPER is using the insecure dev default. "
                + "Set a strong random value: DEVICE_SECRET_PEPPER=$(openssl rand -hex 16)"
            )

        if self.embedding_use_mock:
            errors.append(
                "EMBEDDING_USE_MOCK is true. "
                + "Production/staging requires real embeddings for accurate search. "
                + "Set EMBEDDING_USE_MOCK=false and ensure the embedding model is "
                + "downloaded (HF_HOME must contain the model cache)."
            )

        if self.auth0_enabled:
            if not self.auth0_domain or "your-tenant" in self.auth0_domain:
                errors.append(
                    "AUTH0_DOMAIN is missing or contains the placeholder 'your-tenant'. "
                    + "Set AUTH0_DOMAIN to your real Auth0 tenant domain "
                    + "(e.g. AUTH0_DOMAIN=mycompany.auth0.com)."
                )

        if errors:
            msg = (
                f"\n{'='*60}\n"
                + f"FATAL: Refusing to start in '{self.environment}' mode.\n\n"
                + "\n".join(f"  [{i+1}] {e}" for i, e in enumerate(errors))
                + f"\n\nFix all {len(errors)} issue(s) above before starting.\n"
                + f"{'='*60}"
            )
            logging.critical(msg)
            raise ProductionGuardError(msg)


@lru_cache
def get_settings() -> Settings:
    return Settings()
