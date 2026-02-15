from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    environment: Literal["development", "staging", "production"] = "development"
    log_level: str = "INFO"
    
    database_url: str = "postgresql+asyncpg://heimdex:heimdex_dev_password@localhost:5432/heimdex"
    database_url_sync: str = "postgresql://heimdex:heimdex_dev_password@localhost:5432/heimdex"
    
    opensearch_url: str = "http://localhost:9200"
    opensearch_index_prefix: str = "heimdex"
    
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "heimdex"
    minio_secret_key: str = "heimdex_dev_password"
    minio_secure: bool = False
    
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
    
    search_lexical_top_k: int = 200
    search_vector_top_k: int = 200
    search_rrf_k: int = 60
    search_max_scenes_per_video: int = 4
    search_page_size: int = 20
    ocr_search_enabled: bool = True
    ocr_bm25_boost: float = 0.6
    
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

    # --- Device registration ---
    device_secret_pepper: str = "dev-device-pepper-change-in-production"
    pairing_code_ttl_minutes: int = 10

    # --- CORS ---
    cors_allow_origin_regex: str = (
        r"^https?://"
        r"([a-z0-9][a-z0-9-]{0,}[a-z0-9]\.app\.heimdex\.(co|local)"
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
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
