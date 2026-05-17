"""Settings loader for the product-enumerate-worker.

All env-driven via pydantic-settings, mirroring drive-blur-worker. The
field names with the ``sqs_`` / ``drive_`` prefix come from
:class:`heimdex_worker_sdk.WorkerSettings` so ``build_queue_client``
can resolve them — adding new fields to that base class is the
publish-then-pin protocol per
``feedback_worker_sdk_publish_then_pin``.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---------- queue + auth (shared with worker-sdk) ----------

    queue_backend: str = "sqs"        # "sqs" | "rabbitmq"
    sqs_consumer_enabled: bool = True
    sqs_region: str = "ap-northeast-2"
    # ``heimdex_worker_sdk.build_queue_client`` reads
    # ``settings.sqs_endpoint_url`` unconditionally (passes ``None``
    # when empty so boto picks the default endpoint). Omitting the
    # field would AttributeError at queue construction.
    sqs_endpoint_url: str = ""

    # ---------- S3 ----------
    # Read keyframes (drive-worker output) + write canonical product
    # crops (this worker's output). Same bucket as the rest of the
    # platform; per-org isolation is path-based (org_id prefix).
    s3_region: str = "ap-northeast-2"
    s3_endpoint_url: str = ""           # MinIO local override; empty in prod
    drive_s3_bucket: str = "heimdex-drive"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # The product enumerate queue (provisioned in AWS during Phase 0).
    sqs_product_enumerate_queue_url: str = ""

    # API base URL + Bearer token for /internal/products/* callbacks.
    drive_api_base_url: str = "http://api:8000"
    drive_internal_api_key: str = ""

    # ---------- worker identity ----------

    worker_id: str = "product-enumerate-worker-local"
    worker_lease_seconds: int = 600
    drive_product_enumerate_concurrency: int = 1

    # ---------- model + LLM ----------

    siglip2_model_id: str = "google/siglip2-base-patch16-256"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_timeout_sec: float = 30.0
    openai_max_retries: int = 3
    openai_batch_size: int = 10

    # ---------- pipeline thresholds ----------

    enumeration_version: str = "v1.0"
    enumeration_prompt_version: str = "v1.0"
    max_keyframes_per_video: int = 60
    enum_prominence_floor_pct: float = 0.03
    enum_cluster_cosine_threshold: float = 0.85
    enum_min_supporting_keyframes: int = 2
    enum_min_confidence: float = 0.6

    # ---------- safety ----------

    product_v2_enabled: bool = False
    enumerate_allow_cpu: bool = False  # block CPU mode unless explicit

    # ---------- observability ----------

    log_level: str = "INFO"
    worker_events_enabled: bool = True
    analytics_enabled: bool = True

    @property
    def use_gpu(self) -> bool:
        try:
            import torch
            return bool(torch.cuda.is_available())
        except Exception:
            return False
