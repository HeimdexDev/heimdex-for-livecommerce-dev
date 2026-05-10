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

    # --- Generic OIDC (on-prem) ---
    # When set, these override Auth0 domain derivation. AUTH0_ENABLED
    # remains the master switch for "external OIDC is active".
    # If oidc_issuer is set, JWKS URI and issuer validation use it
    # instead of deriving from auth0_domain.
    oidc_issuer: str = ""       # e.g. "https://keycloak.company.local/realms/heimdex"
    oidc_jwks_uri: str = ""     # auto-discovered from {oidc_issuer}/.well-known/openid-configuration if empty
    oidc_org_claim: str = ""    # claim path for org_id — falls back to auth0_org_claim if empty
    
    # Embedding model configuration
    embedding_model: str = "intfloat/multilingual-e5-large"
    embedding_dimension: int = 1024  # multilingual-e5-large uses 1024 dimensions
    embedding_device: str = "cpu"  # "cpu", "cuda", or "mps" for Apple Silicon
    embedding_use_mock: bool = False  # Set to True to use mock embeddings for testing

    # Visual embedding (SigLIP2) configuration
    visual_embedding_enabled: bool = False  # Enable SigLIP2 visual search at query time
    visual_embedding_model: str = "google/siglip2-base-patch16-256"
    visual_embedding_dimension: int = 768
    
    # Cross-encoder reranker (GPU service)
    reranker_enabled: bool = False
    reranker_service_url: str = ""
    reranker_top_k: int = 20
    reranker_blend_weight: float = 0.7
    reranker_timeout_ms: int = 5000
    reranker_use_mock: bool = False

    search_lexical_top_k: int = 200
    search_vector_top_k: int = 200
    search_rrf_k: int = 20
    search_max_scenes_per_video: int = 4
    search_page_size: int = 20
    # Hard ceiling for per-request page_size overrides (moodboard uses 60).
    # Invariant: search_*_top_k must stay ≥ 3 × search_page_size_max so the
    # RRF candidate pool always exceeds what diversification consumes.
    search_page_size_max: int = 120
    # Search rate limiting — per-(org, user) in-memory sliding window.
    # Keyed on user (not org) so a team of concurrent researchers at
    # one customer doesn't starve each other out of a shared bucket.
    # Ops can raise temporarily via env without a redeploy.
    search_rate_limit_max_requests: int = 60
    search_rate_limit_window_seconds: int = 60
    ocr_search_enabled: bool = True
    ocr_bm25_boost: float = 0.6
    opensearch_facet_size: int = 500

    
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
    face_thumbnail_s3_primary: bool = False
    highlight_reel_enabled: bool = False

    # --- Google Drive connector ---
    drive_connector_enabled: bool = False
    folder_sync_v2_enabled: bool = True  # Folder-level sync settings (watched folders UI)
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

    # Codex F1 Phase 3 — per-service tokens for internal endpoints
    # without a path resource (worker_events, ingest/scenes, etc.).
    # Format: comma-separated ``service_id:token`` pairs, e.g.,
    #   "drive-worker:abc123,blur-worker:def456,worker-events:ghi789"
    # Workers send ``X-Heimdex-Service-Id`` header + their per-service
    # token as the bearer; api validates the bearer matches the
    # expected token for that service. Backward-compat: requests
    # without ``X-Heimdex-Service-Id`` fall back to the legacy
    # ``drive_internal_api_key`` shared bearer (so workers don't
    # need to update before the api change ships).
    # Empty value = service-id auth disabled (legacy bearer only).
    internal_service_tokens: str = ""
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
    drive_caption_model: str = "Qwen/Qwen2.5-VL-7B-Instruct"
    caption_engine: str = "qwen2vl"  # "qwen2vl", "internvl2", "florence2", or "llama_http"

    # --- VLM tag extraction ---
    vlm_tags_enabled: bool = False  # Feature flag: VLM-generated tags instead of rule-based
    ai_tags_enabled: bool = False  # Feature flag: free-form Korean AI tags from VLM

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

    # --- Queue backend ---
    # "sqs" (default, cloud) or "rabbitmq" (on-prem).
    queue_backend: str = "sqs"

    # --- RabbitMQ (on-prem) ---
    rabbitmq_host: str = "localhost"
    rabbitmq_port: int = 5672
    rabbitmq_username: str = "guest"
    rabbitmq_password: str = "guest"
    rabbitmq_vhost: str = "/"
    rabbitmq_queue_prefix: str = "heimdex"

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
    sqs_shorts_render_queue_url: str = ""
    sqs_blur_queue_url: str = ""

    # --- Aircloud GPU worker orchestration ---
    aircloud_enabled: bool = False
    aircloud_api_key: str = ""
    aircloud_endpoint_transcode: str = ""
    aircloud_endpoint_caption: str = ""
    aircloud_endpoint_stt: str = ""
    aircloud_endpoint_ocr: str = ""
    aircloud_endpoint_face: str = ""
    aircloud_endpoint_visual_embed: str = ""
    aircloud_endpoint_blur: str = ""
    aircloud_wake_debounce_seconds: int = 300   # 5 min between wake-up calls per worker
    aircloud_cooldown_checks: int = 3           # 3 × 5 min = 15 min idle before stop

    # --- Closed-vocabulary VMD search (sidecar container) ---
    closed_vocab_enabled: bool = False
    closed_vocab_service_url: str = ""
    closed_vocab_timeout_ms: int = 1000

    # --- PII blur (user-triggered, see app/modules/blur/) ---
    # BLUR_ENABLED is the global kill switch. While false the
    # /api/blur/videos/{id} router returns 404 and no SQS traffic
    # or Aircloud wake-ups are produced.
    blur_enabled: bool = False
    # BLUR_EXPORT_ENABLED gates the NLE-compatible ProRes 4444 layer
    # export subsystem (POST /api/blur/jobs/{id}/export). Keeps the
    # feature dark in envs where drive-blur-worker hasn't been
    # upgraded to the dispatcher version yet.
    blur_export_enabled: bool = False
    blur_max_active_per_org: int = 5       # queued+running cap per org
    blur_lease_seconds: int = 1800         # 30 min worker lease (matches SQS visibility)
    blur_daily_budget_usd_per_org: float = 50.0  # reserved for a later circuit breaker

    # --- Video summary (OpenAI) ---
    openai_api_key: str = ""
    video_summary_enabled: bool = False
    video_summary_model: str = "gpt-4o-mini"

    # --- Image caption (OpenAI gpt-4o) ---
    # Feature flag — when False, image scenes index without captions and the
    # ingest hook becomes a no-op. Safe default.
    image_caption_enabled: bool = False
    image_caption_model: str = "gpt-4o"
    # "low" uses ~85 tokens per image, "high" uses ~170 per 512x512 tile.
    # VMD-level description is fine with "low".
    image_caption_image_detail: Literal["low", "high", "auto"] = "low"
    image_caption_max_concurrency: int = 4
    image_caption_timeout_s: float = 30.0
    # Hard daily dollar ceiling. When exceeded, engine raises
    # BudgetExceededError, service marks scene caption_status=pending so the
    # backfill CLI picks it up after the budget resets.
    image_caption_daily_budget_usd: float = 50.0
    # Used for the pre-call budget reservation. Set above mean per-call cost
    # so burst traffic can't slip past the ceiling.
    image_caption_estimated_cost_per_call_usd: float = 0.012
    # Bump this string (matches openai_prompt.PROMPT_VERSION) when the prompt
    # changes, so we can target re-backfill at a specific prompt generation.
    image_caption_prompt_version: str = "2026-04-13-v1"

    # --- Search analytics ---
    analytics_enabled: bool = True  # Record search events to Postgres
    analytics_export_enabled: bool = False  # Nightly S3 Parquet export
    analytics_s3_bucket: str = ""  # Defaults to drive_s3_bucket if empty
    analytics_s3_prefix: str = "analytics"
    analytics_bq_enabled: bool = False  # Also load to BigQuery after S3 export
    analytics_bq_project: str = ""  # Required when ANALYTICS_BQ_ENABLED=true
    analytics_bq_dataset: str = "search_analytics"

    # --- Proxy-pack export ---
    export_max_size_bytes: int = 2_147_483_648  # 2 GB
    export_max_clips: int = 100
    export_max_proxies: int = 20
    export_expiry_days: int = 3
    shorts_render_expiry_days: int = 3

    # --- Auto-shorts (mode-aware AI clip selection over the existing
    # shorts render pipeline). All flags off by default — the router 404s
    # while ``auto_shorts_enabled`` is False so an in-progress rollout
    # can't leak through. Caption flags are deferred to phase 4.
    auto_shorts_enabled: bool = False
    auto_shorts_rate_limit_per_hour: int = 10
    auto_shorts_min_video_duration_sec: int = 300

    # --- Auto-shorts LLM scene picker (Option C from
    # .claude/plans/shorts-auto-llm-selection.md). LLM replaces the
    # pure-function scorer when ``auto_shorts_llm_enabled`` is true AND
    # the request hashes into the rollout bucket. On any LLM error
    # (timeout, budget, 4xx, JSON/schema failure, hallucinated scene_id)
    # the service silently falls back to the pure scorer — the user-
    # facing endpoint must never 5xx.
    auto_shorts_llm_enabled: bool = False
    auto_shorts_llm_model: str = "gpt-4o-mini"
    auto_shorts_llm_max_scenes: int = 50  # matches video_summary cap
    auto_shorts_llm_daily_budget_usd: float = 25.0
    auto_shorts_llm_estimated_cost_per_call_usd: float = 0.003
    auto_shorts_llm_timeout_sec: float = 8.0
    auto_shorts_llm_rollout_pct: int = 0  # 0-100, hashed on (org_id, video_id)
    auto_shorts_llm_prompt_version: str = "2026-04-24-v1"

    # --- Auto-shorts product mode v2 (per-video product catalog +
    # SAM2/SigLIP2 tracking + product-anchored clip output). All flags
    # off by default; product-mode requests fall back to the v1
    # heuristic+LLM path when ``auto_shorts_product_v2_enabled`` is
    # False or the org is outside the rollout bucket. Plan:
    # ``.claude/plans/shorts-auto-product-v2.md``.
    #
    # Cost cap is a SEPARATE bucket from auto_shorts_llm /
    # image_caption / video_summary — this pipeline burns Aircloud GPU
    # minutes (SAM2 + SigLIP2) plus gpt-4o-mini for enumeration and
    # subset picking, and we want the per-feature ledger to be
    # interpretable.
    auto_shorts_product_v2_enabled: bool = False
    auto_shorts_product_v2_rollout_pct: int = 0  # 0-100; hashed on org_id

    # Per-org per-day cost cap; 80% triggers Slack warn, 100% returns 402.
    auto_shorts_product_v2_daily_budget_usd: float = 50.0
    auto_shorts_product_v2_budget_alert_pct: int = 80

    # Concurrency cap. (N+1)-th in-flight scan from the same org
    # returns 429. Counts rows across all modes (scan_order,
    # enumerate, render_child) in ACTIVE_SCAN_STAGES — see
    # ``ProductScanJobRepository.count_active_for_org``.
    #
    # Bumped 3→10 on 2026-05-06 after the cap was tripping operators
    # mid-iteration on staging. Cost is gated separately by
    # ``auto_shorts_product_v2_daily_budget_usd``; concurrency just
    # determines how many can be in-flight simultaneously, not total
    # spend. 10 leaves comfortable headroom for an operator who has
    # 2-3 wizard runs queued + an enumeration scan + a half-finished
    # rerender, without paper-cutting them on parallel work.
    auto_shorts_product_v2_max_concurrent_per_org: int = 10

    # Cap on LLM-vision calls per video (60 keyframes × 1 batch of 10 ≈
    # 6 calls = ~$0.03 with gpt-4o-mini). Bound the worst-case spend on
    # multi-hour livecommerce streams.
    auto_shorts_product_v2_max_keyframes_per_video: int = 60

    # Allowed clip durations in seconds. Locked to {30, 60, 90} per
    # plan §1 to match Reels / Shorts / TikTok native lengths. Comma-
    # separated env value parses to set; mirrored on the migration's
    # CHECK constraint and the contracts ``DurationPresetSec`` literal.
    auto_shorts_product_v2_duration_presets_sec: str = "30,60,90"

    # Pipeline + prompt versions. Bumping any of these invalidates
    # cached catalog entries (the API surfaces a "newer scan available"
    # banner; never auto-rescans). Kept in sync with:
    #   * heimdex_media_contracts.product.EnumerationPrompt.VERSION
    #   * heimdex_media_pipelines.product_enum.ENUMERATION_VERSION
    #   * heimdex_media_pipelines.product_track.TRACKER_VERSION
    auto_shorts_product_v2_enumeration_prompt_version: str = "v1.0"
    auto_shorts_product_v2_enumeration_version: str = "v1.0"
    auto_shorts_product_v2_tracker_version: str = "v1.0"

    # ---------- v0.15.0 STT-pivot track mode ----------
    #
    # ``"sam2"`` (default) preserves existing behavior — the
    # ``shorts_auto_product`` orchestrator fans out to
    # ``product-track-worker`` via SQS for per-scene SAM2 mask
    # propagation. ``"stt"`` swaps in the in-process STT pipeline at
    # ``shorts_auto_product/track_stt``: BM25 mention extraction over
    # OpenSearch, gpt-4o-mini chunk scoring, no GPU. Flip to ``"stt"``
    # only after the catalog backfill of ``spoken_aliases`` is complete
    # for the org (PR 1b).
    #
    # See ``.claude/plans/shorts-auto-product-stt-pivot.md`` for the
    # full migration plan, including the prod rollback path which
    # requires keeping the SAM2 worker deployable for at least 30 days
    # post-flip.
    auto_shorts_product_v2_track_mode: str = "sam2"

    # Idempotency window for the scan endpoint — same (video_id,
    # user_id) within this window returns the existing job_id.
    auto_shorts_product_v2_scan_idempotency_seconds: int = 60

    # Worker queues. Empty strings disable enqueue (workers can be
    # provisioned ahead of being wired up).
    sqs_product_enumerate_queue_url: str = ""
    sqs_product_track_queue_url: str = ""

    # Aircloud container UUIDs (from infra provisioning). drive-worker's
    # gpu_orchestrator extends to monitor these so first message wakes
    # the endpoint within ~5 min and 15 min idle stops it.
    aircloud_endpoint_product_enumerate: str = ""
    aircloud_endpoint_product_track: str = ""

    # SigLIP2 variant pinned to the deployed drive-visual-embed-worker
    # model. Used by the workers, but mirrored here so the API can
    # cross-check at startup that contracts agree on the same shape
    # before the worker images bake the pin.
    auto_shorts_product_v2_siglip2_model_id: str = "google/siglip2-base-patch16-256"

    # Externally-reachable base URL for ``/internal/products/*``
    # callbacks. Workers POST here. Empty string disables enqueue.
    # Local dev: ``http://api:8000``. Staging:
    # ``https://devorg.app.heimdexdemo.dev``. Production: per-tenant.
    auto_shorts_product_v2_callback_base_url: str = ""

    # Per-stage worker lease lengths (seconds). Heartbeats extend the
    # lease by this amount on every progress callback. Match the SQS
    # visibility timeouts on the corresponding queues.
    auto_shorts_product_v2_enumerate_lease_seconds: int = 600
    auto_shorts_product_v2_track_lease_seconds: int = 1800

    # --- Phase 4 wizard / child runner ---
    #
    # Bounded concurrency for the in-API-process child render runner
    # (services/api/app/modules/shorts_auto_product/children/runner.py).
    # Children are CPU-light (subset_pick + stitch_plan + 1 HTTP call to
    # /render) but should not starve request handlers under load. If
    # render-enqueue latency rises, drop to 2.
    auto_shorts_product_v2_child_runner_max_concurrency: int = 4
    # Poll interval for the runner loop. 5s is fast enough for the
    # wizard's 3s polling cadence to feel near-instant; lower values
    # burn CPU on idle replicas.
    auto_shorts_product_v2_child_runner_poll_seconds: float = 5.0
    # Lease length for child claims. Children are fast (subset_pick is
    # bounded by parent's appearances; stitch_plan is O(N); render
    # enqueue is one HTTP call), so a short lease catches a wedged
    # replica quickly without spuriously stealing work from a healthy
    # one.
    auto_shorts_product_v2_child_lease_seconds: int = 300
    # Master switch for the child runner loop. Default ON in prod;
    # disable to suspend wizard fan-out without redeploying (e.g. while
    # debugging a render-side incident).
    auto_shorts_product_v2_child_runner_enabled: bool = True

    # Eager parent promotion: after every child terminal transition,
    # the runner immediately atomically promotes
    # ``fanned_out → committed`` if all siblings are terminal.
    # Eliminates the "user closed browser before last child finished →
    # parent stuck forever" failure mode that the lazy block in
    # ``service.py::get_scan_order_status`` was the only safety net for.
    # Default ON; flag exists for emergency disable per
    # .claude/plans/shorts-auto-product-cap-stuck-fix.md (PR 2). The
    # lazy block stays as belt-and-suspenders regardless of this flag.
    auto_shorts_product_v2_eager_parent_promotion_enabled: bool = True

    # PR 3: self-healing runner. When True, the runner's poll matches
    # both queued render_children AND expired-lease assembling/rendering
    # children. Re-claiming the latter recovers from API replica
    # restarts that orphan rows mid-process — eliminates the
    # "API restart kills runner mid-claim → child stuck in assembling
    # forever" failure mode (Mechanism A in the plan). Default ON; the
    # legacy ``find_queued_render_children`` path is preserved for the
    # flag-off fallback. See
    # .claude/plans/shorts-auto-product-cap-stuck-fix.md (PR 3 of 3).
    auto_shorts_product_v2_self_heal_enabled: bool = True

    # PR 2 of multi-product wizard: when False, the scan-order endpoint
    # rejects ``len(catalog_entry_ids) > 1`` with 422. Single-pick still
    # works through either ``catalog_entry_id`` (legacy) or
    # ``catalog_entry_ids=[X]``. Default ON; emergency disable per
    # .claude/plans/wizard-multi-product-select.md.
    auto_shorts_product_v2_multi_select_enabled: bool = True

    # Wizard idempotency window. Same shape as the legacy
    # ``auto_shorts_product_v2_scan_idempotency_seconds`` but keyed on
    # the canonical-JSON ``settings_hash`` so two different sets of
    # wizard inputs don't collide.
    auto_shorts_product_v2_scan_order_idempotency_seconds: int = 60

    # Master flag for the wizard's SQS publish step. Default OFF: the
    # service creates parent rows in DB but does NOT publish to
    # ``heimdex-product-track-queue`` until this flips. Required so
    # we can roll out the API code that knows about scan_order
    # BEFORE the worker on Aircloud is rebuilt with v0.14.0
    # contracts. Flipping early would fill the worker's DLQ with
    # messages it can't parse. Once the worker image is bumped +
    # redeployed, flip this to True (per-env via Aircloud config or
    # docker-compose .env override).
    auto_shorts_product_v2_publish_scan_order_enabled: bool = False

    # ---------- v0.16.0 STT-first enumeration (parallel to vision) ----------
    #
    # Inline in-process LLM enumeration over the full transcript.
    # Runs alongside the existing vision keyframe enumerator on every
    # ``POST /scan``; the wizard polls a merged catalog. No GPU, no
    # SQS, no worker. ~$0.003/video on gpt-4o-mini, roughly 10× cheaper
    # than the vision path.
    #
    # See ``.claude/plans/shorts-auto-product-stt-enum-2026-05-06.md``.
    auto_shorts_product_v2_stt_enum_enabled: bool = False
    auto_shorts_product_v2_stt_enum_model: str = "gpt-4o-mini"
    # Bound the asyncio fan-out from /scan into the LLM. STT enum is
    # fire-and-forget; this caps how many concurrent enumeration calls
    # an api replica spawns. Defaults match image_caption's pattern.
    auto_shorts_product_v2_stt_enum_max_concurrency: int = 4
    # Mirrors heimdex_media_contracts.product.TranscriptEnumerationPrompt.VERSION.
    # Bumping in lockstep is the goldens-eval gate (PR 5 of plan).
    auto_shorts_product_v2_stt_enum_prompt_version: str = "v1.0"
    # Truncation guardrail. ~80k tokens covers 2-3hr of dense Korean
    # transcript before we hit gpt-4o-mini's context. Multi-pass
    # chunking would land in Phase 8 if a video genuinely exceeds it.
    auto_shorts_product_v2_stt_enum_max_transcript_tokens: int = 80000
    # Per-call wall-time ceiling. Trips for transcripts that genuinely
    # take that long; surface as ``enumeration_llm_failed``.
    auto_shorts_product_v2_stt_enum_timeout_s: float = 90.0

    # --- Auto-shorts: caption-source switch ---
    # Decoupled from OS speaker_transcript on 2026-05-07: Whisper
    # post-render is the only caption source for auto-shorts so a
    # resplit/indexing drift in OS can never paint wrong text onto
    # a rendered short again. Set this to True ONLY for emergency
    # rollback — flipping it back on revives the historical
    # speaker_transcript-derived subtitle path inside
    # ``track_stt/composition_builder.py``. Plan to delete this
    # flag + the dead-code path after a 2-week soak with the new
    # behavior on prod.
    auto_shorts_product_v2_legacy_os_subtitles_enabled: bool = False

    # --- Auto-shorts: storyboard composition (Tier B + Tier C) ---
    # When True, the STT pipeline composes the final clip from
    # role-labelled fragments (HOOK / INTRO / DETAIL / CTA) chosen
    # by a ``StoryboardPicker`` instead of a single contiguous
    # window. Default False ships the picker module as dead code
    # — flip on staging first to soak. See plan
    # ``track_stt/storyboard/__init__.py``.
    auto_shorts_product_v2_storyboard_mode_enabled: bool = False
    # ``"heuristic"`` = Tier B picker over already-scored chunks
    # (no extra LLM cost). ``"llm"`` = Tier C director (future,
    # not yet implemented). Both implementations satisfy the same
    # ``StoryboardPicker`` Protocol; the factory in
    # ``storyboard/factory.py`` instantiates the right one.
    auto_shorts_product_v2_storyboard_picker: str = "heuristic"
    # Slot duration budgets in milliseconds. Defaults sum to 53s
    # leaving ~7s headroom for a 60s target. Tunable on staging
    # without code change.
    auto_shorts_product_v2_storyboard_hook_ms: int = 8_000
    auto_shorts_product_v2_storyboard_intro_ms: int = 12_000
    auto_shorts_product_v2_storyboard_detail_ms: int = 25_000
    auto_shorts_product_v2_storyboard_cta_ms: int = 8_000
    # Shadow mode — runs the storyboard picker alongside the
    # legacy clip_selector and emits a diff event for telemetry,
    # but the LEGACY plan is what produces the actual render.
    # Lets us validate Tier B's output before flipping the real
    # switch. Has no effect when
    # ``auto_shorts_product_v2_storyboard_mode_enabled`` is True.
    auto_shorts_product_v2_storyboard_shadow_mode: bool = False

    # --- Auto-shorts: storyboard Tier C (LLM director) ---
    # Plan: ``.claude/plans/storyboard-tier-c-llm-picker-2026-05-07.md``.
    # Activated by setting
    # ``auto_shorts_product_v2_storyboard_picker = "llm"`` (the master
    # ``..._storyboard_mode_enabled`` flag must also be true). Default off:
    # the factory builds ``HeuristicStoryboardPicker`` until the picker
    # type is flipped.
    #
    # Cost shape: ~$0.0004 per scan with gpt-4o-mini (~1250 input tokens
    # + ~300 output tokens). $5/day budget = ~12,500 scans/day cap.
    # Separate bucket from chunk_scorer / image_caption / whisper /
    # video_summary per the existing convention (every LLM consumer
    # owns its budget bucket so exhaustion in one path doesn't starve
    # the others).
    auto_shorts_product_v2_storyboard_llm_model: str = "gpt-4o-mini"
    # Per-call timeout (asyncio.wait_for + openai SDK timeout). 5s
    # is comfortably above gpt-4o-mini's median 1-3s end-to-end for
    # ~300 output tokens. On timeout the picker falls back to Tier B
    # silently.
    auto_shorts_product_v2_storyboard_llm_timeout_s: float = 5.0
    auto_shorts_product_v2_storyboard_llm_daily_budget_usd: float = 5.0
    # Mirrors ``llm_prompt.PROMPT_VERSION``. Bumped in lockstep on every
    # system-prompt edit; goldens snapshot cache keys on this. Drift
    # between this env var and the module constant is a misconfig
    # signal — the picker logs a WARNING and continues with the
    # module's value.
    auto_shorts_product_v2_storyboard_llm_prompt_version: str = "v2"

    # --- Auto-shorts: post-render Whisper subtitle refinement ---
    # Plan: ``.claude/plans/auto-shorts-whisper-subtitles-2026-05-06.md``
    # Off-by-default master flag. Even with the column migration
    # (056) in place, no refinement fires until this flips to True.
    auto_shorts_product_v2_whisper_refine_enabled: bool = False
    # 0-100, hashed on org_id (mirrors auto_shorts_llm_rollout_pct
    # behavior). Allows progressive rollout without an org-specific
    # allowlist. 0 = nobody, 100 = everyone with the flag on.
    auto_shorts_product_v2_whisper_rollout_pct: int = 0
    # OpenAI model name. ``whisper-1`` is the only model currently
    # exposing word-level timestamps via ``timestamp_granularities``.
    # Verify pricing + capability before changing.
    auto_shorts_product_v2_whisper_model: str = "whisper-1"
    # ISO 639-1 language code pinned on every transcription request.
    # Korean livecommerce defaults to ``ko``; multi-language tenants
    # need a per-org override (not in scope for v1).
    auto_shorts_product_v2_whisper_language: str = "ko"
    # **Separate budget bucket** from auto_shorts_llm,
    # image_caption, and auto_shorts_product_v2 enumeration. Daily
    # USD ceiling enforced by an in-memory tracker; hitting it
    # silently skips refinement until UTC rollover.
    auto_shorts_product_v2_whisper_daily_budget_usd: float = 5.0
    # Hard timeout on each Whisper API call. Larger than the LLM
    # timeout because audio uploads add measurable latency on
    # slower networks.
    auto_shorts_product_v2_whisper_timeout_s: float = 60.0
    # Separate timeout for the S3 download that precedes the
    # Whisper call. A 25 MB MP4 on a slow link can outlast the
    # API timeout — keep them split so log triage points at the
    # right hop.
    auto_shorts_product_v2_whisper_s3_download_timeout_s: float = 30.0

    # --- Auto-shorts: overlay-mode caption flow ---
    # Plan: ``.claude/plans/auto-shorts-overlay-mode-2026-05-07.md``.
    # When ON: parents render with empty subtitles (no burn-in);
    # Whisper post-render writes cues to the parent's
    # ``input_spec.subtitles`` + sets ``refinement_source='whisper'``
    # in place (no child render created); the FE renders cues via a
    # WYSIWYG DOM overlay; ``/rerender`` produces an export child
    # that burns subs in but does NOT replace the parent (no
    # ``replaced_by`` link). The parent stays canonical for editing.
    # When OFF (default, prod-safe): existing behavior — Whisper
    # creates a refined child render and links via ``replaced_by``.
    # Staging-only feature; auto-shorts product mode is staging-gated
    # at the feature level. Drives BOTH the refinement-write path AND
    # the rerender-link skip — single switch, both behaviors cohere.
    auto_shorts_product_v2_overlay_mode_enabled: bool = False

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
            has_auth0 = self.auth0_domain and "your-tenant" not in self.auth0_domain
            has_oidc = bool(self.oidc_issuer)
            if not has_auth0 and not has_oidc:
                errors.append(
                    "AUTH0_DOMAIN or OIDC_ISSUER must be configured when AUTH0_ENABLED=true. "
                    + "Set AUTH0_DOMAIN for Auth0 (e.g. mycompany.auth0.com) or "
                    + "OIDC_ISSUER for a generic OIDC provider "
                    + "(e.g. https://keycloak.company.local/realms/heimdex)."
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
