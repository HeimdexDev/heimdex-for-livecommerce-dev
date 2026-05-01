"""Settings loader for the product-track-worker.

Mirrors product-enumerate-worker's settings module — same env naming
conventions, same backward-compat fields from
:class:`heimdex_worker_sdk.WorkerSettings` so ``build_queue_client``
resolves them, same SigLIP2 variant pin (drift breaks the OS coarse
pre-filter at /scenes-by-visual-similarity).

Track-specific additions:
* ``sqs_product_track_queue_url`` — the queue this worker polls.
* ``sam2_model_id`` — SAM2 checkpoint (default
  ``facebook/sam2-hiera-base-plus`` per plan §6.2 calibration starting
  point; may flip to ``hiera-large`` if staging goldens fall short of
  the IoU floor).
* Tracking thresholds — every threshold in
  :class:`heimdex_media_pipelines.product_track.config.TrackingConfig`
  is exposed as an env-overridable field. Keeping them here (rather
  than only in the lib's defaults) so on-call can tune any single
  knob without a code change.
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

    queue_backend: str = "sqs"
    sqs_consumer_enabled: bool = True
    sqs_region: str = "ap-northeast-2"

    # ---------- S3 ----------

    s3_region: str = "ap-northeast-2"
    s3_endpoint_url: str = ""
    drive_s3_bucket: str = "heimdex-drive"
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""

    # The product track queue (provisioned in AWS during Phase 0; ARN
    # added to ``heimdex-aircloud-worker`` in Phase 2.5c IAM update).
    sqs_product_track_queue_url: str = ""

    # API base URL + Bearer token for /internal/products/* callbacks
    # AND the Phase 3b read endpoints (scenes-by-visual-similarity,
    # scenes-content). The same bearer covers both.
    drive_api_base_url: str = "http://api:8000"
    drive_internal_api_key: str = ""

    # F1 Phase 3 per-service identity (optional). When set, the worker
    # sends ``X-Heimdex-Service-Id: <this>`` + per-service token. When
    # empty, falls back to the legacy global bearer (still valid; api
    # accepts both paths during the rollout).
    internal_service_id: str = ""

    # ---------- worker identity ----------

    worker_id: str = "product-track-worker-local"
    # Track jobs are heavier than enumerate jobs (SAM2 + per-scene
    # video decode) — generous lease so a long-running track doesn't
    # auto-fail mid-flight. Matches the queue's 1800s visibility
    # timeout from plan §11 queue setup.
    worker_lease_seconds: int = 1800
    drive_product_track_concurrency: int = 1

    # ---------- model + LLM ----------

    siglip2_model_id: str = "google/siglip2-base-patch16-256"
    # SAM2 checkpoint. ``base-plus`` is the calibration starting point
    # (smaller image footprint than ``large``, faster cold-starts on
    # Aircloud). If the goldens IoU floor (≥0.6 mean) fails, plan §6.2
    # says swap to DINOv2 *or* upgrade to hiera-large. Pin update is a
    # one-line config bump here.
    sam2_model_id: str = "facebook/sam2-hiera-base-plus"

    # OpenAI is used for the subset picker (plan §6.2 step 7) — small
    # gpt-4o-mini call per job to choose the final ~3-5 windows.
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    openai_timeout_sec: float = 30.0
    openai_max_retries: int = 3

    # ---------- retrieval thresholds ----------

    coarse_prefilter_threshold: float = 0.45
    precise_pass_threshold: float = 0.72
    coarse_top_k: int = 60

    # ---------- SAM2 sampling cadence ----------

    sam2_sample_fps: int = 5

    # ---------- window assembly thresholds ----------

    min_window_duration_ms: int = 1500
    min_avg_bbox_area_pct: float = 0.02
    min_avg_confidence: float = 0.7
    merge_gap_threshold_ms: int = 2000
    max_windows_per_product: int = 30

    # ---------- subset picker weights ----------

    score_weight_prominence: float = 0.35
    score_weight_narration: float = 0.25
    score_weight_ocr: float = 0.15
    score_weight_duration_fitness: float = 0.15
    score_weight_spread_bonus: float = 0.10
    subset_duration_overshoot_factor: float = 1.05

    # ---------- pipeline version strings ----------

    tracker_version: str = "v1.0"
    subset_picker_version: str = "v1.0"

    # ---------- safety ----------

    product_v2_enabled: bool = False
    track_allow_cpu: bool = False  # block CPU mode unless explicit

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
