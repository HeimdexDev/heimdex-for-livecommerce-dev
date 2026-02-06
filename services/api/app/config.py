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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    return Settings()
