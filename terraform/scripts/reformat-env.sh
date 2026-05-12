#!/usr/bin/env bash
set -euo pipefail

# EC2에서 실행: 기존 flat .env를 섹션별로 재정렬
# Usage: ./reformat-env.sh [input] [output]
#   input  : 원본 .env 경로 (default: /opt/heimdex/.env)
#   output : 출력 경로     (default: stdout, -i 로 in-place)

INPUT="${1:-/opt/heimdex/dev-heimdex-for-livecommerce/.env}"
OUTPUT="${2:-}"

if [[ ! -f "$INPUT" ]]; then
  echo "ERROR: $INPUT not found" >&2
  exit 1
fi

declare -A VARS

while IFS= read -r line; do
  [[ -z "$line" || "$line" =~ ^# ]] && continue
  key="${line%%=*}"
  val="${line#*=}"
  VARS["$key"]="$val"
done < "$INPUT"

emit() {
  local key="$1"
  if [[ -n "${VARS[$key]+x}" ]]; then
    echo "${key}=${VARS[$key]}"
    unset 'VARS[$key]'
  fi
}

section() {
  echo ""
  echo "# ── $1 ──────────────────────────────────────────────────────"
}

{
  DOMAIN_VAL="${VARS[DOMAIN]:-unknown}"
  ENV_VAL="${VARS[ENVIRONMENT]:-production}"
  echo "# ── Heimdex ${ENV_VAL} — ${DOMAIN_VAL} ──────────────────────────"
  echo "# Reformatted by reformat-env.sh"

  section "Basic"
  emit ENVIRONMENT
  emit LOG_LEVEL
  emit ALLOWED_HOSTS
  emit ENABLE_DEV_REFRESH

  section "Domain / TLS"
  emit DOMAIN
  emit WILDCARD_DOMAIN
  emit CERTBOT_EMAIL

  section "Postgres"
  emit POSTGRES_HOST
  emit POSTGRES_PORT
  emit POSTGRES_USER
  emit POSTGRES_DB

  section "OpenSearch"
  emit OPENSEARCH_URL
  emit OPENSEARCH_INDEX_PREFIX
  emit OPENSEARCH_JAVA_OPTS

  section "Auth / JWT"
  emit AUTH_COOKIE_SECURE
  emit AUTH_COOKIE_SAMESITE
  emit AUTH_COOKIE_DOMAIN
  emit JWT_ALGORITHM
  emit JWT_EXPIRATION_HOURS
  emit JWT_SECRET_KEY

  section "Auth0"
  emit AUTH0_ENABLED
  emit AUTH0_DOMAIN
  emit AUTH0_AUDIENCE
  emit AUTH0_ALGORITHMS
  emit AUTH0_ORG_CLAIM

  section "CORS"
  emit CORS_ALLOW_ORIGIN_REGEX
  emit CORS_EXTRA_ORIGINS

  section "Google OAuth"
  emit GOOGLE_OAUTH_CLIENT_ID
  emit GOOGLE_OAUTH_CLIENT_SECRET
  emit GOOGLE_OAUTH_REDIRECT_URI

  section "S3 / MinIO"
  emit MINIO_ENDPOINT
  emit MINIO_SECURE
  emit MINIO_ACCESS_KEY
  emit MINIO_SECRET_KEY
  emit DRIVE_S3_BUCKET
  emit S3_REGION

  section "Embedding"
  emit EMBEDDING_MODEL
  emit EMBEDDING_DIMENSION
  emit EMBEDDING_DEVICE
  emit EMBEDDING_USE_MOCK

  section "Search Tuning"
  emit SEARCH_LEXICAL_TOP_K
  emit SEARCH_VECTOR_TOP_K
  emit SEARCH_RRF_K
  emit SEARCH_MAX_SCENES_PER_VIDEO
  emit SEARCH_PAGE_SIZE
  emit SEARCH_DEFAULT_MODE
  emit OCR_SEARCH_ENABLED
  emit OCR_BM25_BOOST

  section "SQS"
  emit SQS_ENABLED
  emit SQS_ENDPOINT_URL
  emit SQS_REGION
  emit SQS_CONSUMER_ENABLED
  emit SQS_PROCESSING_QUEUE_URL
  emit SQS_CAPTION_QUEUE_URL
  emit SQS_STT_QUEUE_URL
  emit SQS_OCR_QUEUE_URL
  emit SQS_TRANSCODE_QUEUE_URL
  emit SQS_FACE_QUEUE_URL
  emit SQS_VISUAL_EMBED_QUEUE_URL
  emit SQS_EXPORT_QUEUE_URL
  emit SQS_SHORTS_RENDER_QUEUE_URL
  emit SQS_BLUR_QUEUE_URL
  emit SQS_PRODUCT_ENUMERATE_QUEUE_URL

  section "Aircloud GPU"
  emit AIRCLOUD_ENABLED
  emit AIRCLOUD_API_KEY
  emit AIRCLOUD_WAKE_DEBOUNCE_SECONDS
  emit AIRCLOUD_COOLDOWN_CHECKS
  emit AIRCLOUD_ENDPOINT_TRANSCODE
  emit AIRCLOUD_ENDPOINT_CAPTION
  emit AIRCLOUD_ENDPOINT_STT
  emit AIRCLOUD_ENDPOINT_OCR
  emit AIRCLOUD_ENDPOINT_FACE
  emit AIRCLOUD_ENDPOINT_VISUAL_EMBED
  emit AIRCLOUD_ENDPOINT_BLUR
  emit AIRCLOUD_ENDPOINT_PRODUCT_ENUMERATE

  section "Reranker"
  emit RERANKER_ENABLED
  emit RERANKER_SERVICE_URL
  emit RERANKER_TIMEOUT_MS
  emit RERANKER_USE_MOCK

  section "Drive Worker"
  emit DRIVE_CONNECTOR_ENABLED
  emit DRIVE_ENRICHMENT_ENABLED
  emit DRIVE_OCR_ENABLED
  emit DRIVE_STT_ENABLED
  emit DRIVE_INTERNAL_API_KEY
  emit DRIVE_SA_ENCRYPTION_KEY
  emit FOLDER_SYNC_V2_ENABLED
  emit DRIVE_WORKER_POLL_INTERVAL_SECONDS
  emit DRIVE_WORKER_GLOBAL_CONCURRENCY
  emit DRIVE_WORKER_PER_ORG_CONCURRENCY
  emit DRIVE_TEMP_DISK_BUDGET_GB
  emit DRIVE_TEMP_DIR
  emit DRIVE_PROXY_MAX_HEIGHT
  emit DRIVE_PROXY_CRF
  emit DRIVE_PROXY_PRESET
  emit DRIVE_PROXY_AUDIO_BITRATE
  emit DRIVE_PROXY_MAX_BITRATE
  emit DRIVE_PROXY_BUFSIZE
  emit IMAGE_PROCESSING_ENABLED
  emit DRIVE_TRANSCODE_MODE
  emit DRIVE_API_BASE_URL

  section "Drive STT"
  emit DRIVE_STT_MODEL
  emit DRIVE_STT_LANGUAGE
  emit DRIVE_STT_DIARIZATION_ENABLED
  emit DRIVE_STT_MIN_SPEAKERS
  emit DRIVE_STT_MAX_SPEAKERS

  section "Caption"
  emit SCENE_CAPTION_ENABLED
  emit CAPTION_ENGINE
  emit DRIVE_CAPTION_MODEL

  section "Feature Flags"
  emit VISUAL_EMBEDDING_ENABLED
  emit VLM_TAGS_ENABLED
  emit AI_TAGS_ENABLED
  emit DRIVE_SPEECH_SPLIT_ENABLED
  emit FACE_THUMBNAIL_S3_PRIMARY
  emit HIGHLIGHT_REEL_ENABLED
  emit VIDEO_SUMMARY_ENABLED
  emit YOUTUBE_ENABLED

  section "Face Detection"
  emit FACE_MATCH_THRESHOLD

  section "Image Caption"
  emit IMAGE_CAPTION_ENABLED
  emit IMAGE_CAPTION_MODEL
  emit IMAGE_CAPTION_IMAGE_DETAIL
  emit IMAGE_CAPTION_MAX_CONCURRENCY
  emit IMAGE_CAPTION_TIMEOUT_S
  emit IMAGE_CAPTION_DAILY_BUDGET_USD
  emit IMAGE_CAPTION_ESTIMATED_COST_PER_CALL_USD
  emit IMAGE_CAPTION_PROMPT_VERSION

  section "Auto Shorts"
  emit AUTO_SHORTS_ENABLED
  emit AUTO_SHORTS_RATE_LIMIT_PER_HOUR
  emit AUTO_SHORTS_MIN_VIDEO_DURATION_SEC
  emit AUTO_SHORTS_LLM_ENABLED
  emit AUTO_SHORTS_LLM_MODEL
  emit AUTO_SHORTS_LLM_MAX_SCENES
  emit AUTO_SHORTS_LLM_DAILY_BUDGET_USD
  emit AUTO_SHORTS_LLM_ESTIMATED_COST_PER_CALL_USD
  emit AUTO_SHORTS_LLM_TIMEOUT_SEC
  emit AUTO_SHORTS_LLM_ROLLOUT_PCT
  emit AUTO_SHORTS_LLM_PROMPT_VERSION

  section "Blur"
  emit BLUR_ENABLED
  emit BLUR_EXPORT_ENABLED
  emit BLUR_MAX_ACTIVE_PER_ORG
  emit BLUR_LEASE_SECONDS
  emit BLUR_DAILY_BUDGET_USD_PER_ORG

  section "Agent"
  emit AGENT_INGEST_ENABLED
  emit AGENT_API_KEY
  emit AGENT_API_KEY_MODE
  emit AGENT_INGEST_MAX_SCENES
  emit AGENT_INGEST_MAX_TRANSCRIPT_CHARS
  emit PAIRING_CODE_TTL_MINUTES
  emit AGENT_INTENTS_ENABLED
  emit AGENT_INTENT_TTL_MINUTES
  emit AGENT_INTENT_MAX_PER_ORG
  emit AGENT_INTENT_EXCHANGE_MAX_ATTEMPTS

  section "Ingest Safety"
  emit INGEST_REQUIRE_TIMESTAMP
  emit INGEST_TIMESTAMP_SKEW_SECONDS
  emit INGEST_REQUIRE_IDEMPOTENCY
  emit INGEST_IDEMPOTENCY_TTL_SECONDS

  section "Export"
  emit EXPORT_MAX_SIZE_BYTES
  emit EXPORT_MAX_CLIPS
  emit EXPORT_MAX_PROXIES
  emit EXPORT_EXPIRY_DAYS

  section "Analytics"
  emit ANALYTICS_ENABLED
  emit ANALYTICS_EXPORT_ENABLED
  emit ANALYTICS_S3_BUCKET
  emit ANALYTICS_S3_PREFIX
  emit ANALYTICS_BQ_ENABLED
  emit ANALYTICS_BQ_PROJECT
  emit ANALYTICS_BQ_DATASET

  section "YouTube"
  emit YOUTUBE_S3_BUCKET
  emit YOUTUBE_SYNC_INTERVAL_SECONDS
  emit YOUTUBE_DOWNLOAD_FORMAT
  emit YOUTUBE_RATE_LIMIT_SLEEP
  emit YOUTUBE_RATE_LIMIT_MAX_SLEEP
  emit YOUTUBE_MAX_CONCURRENT_DOWNLOADS
  emit YOUTUBE_AUTO_DELETE_ORIGINALS
  emit YOUTUBE_ORIGINAL_TTL_DAYS
  emit YOUTUBE_COOKIES_PATH
  emit YOUTUBE_COOKIES_HOST_DIR

  section "Web (build args)"
  emit NEXT_PUBLIC_API_URL
  emit NEXT_PUBLIC_AUTH0_ENABLED
  emit NEXT_PUBLIC_AUTH0_DOMAIN
  emit NEXT_PUBLIC_AUTH0_AUDIENCE
  emit NEXT_PUBLIC_AUTH0_CLIENT_ID
  emit NEXT_PUBLIC_AUTH0_ORGANIZATION
  emit NEXT_PUBLIC_GA_MEASUREMENT_ID
  emit NEXT_PUBLIC_EXPORT_SHORTS_EDITOR_V2_ENABLED
  emit AGENT_UPDATE_MANIFEST_URL

  section "Container Registry"
  emit REGISTRY
  emit IMAGE_TAG

  section "HuggingFace"
  emit HF_HOME
  emit HF_ACCESS_TOKEN

  section "Secrets (DB)"
  emit DATABASE_URL
  emit DATABASE_URL_SYNC

  section "Secrets (API Keys)"
  emit OPENAI_API_KEY
  emit DEVICE_SECRET_PEPPER

  # 템플릿에 없는 변수가 남아있으면 마지막에 출력
  if [[ ${#VARS[@]} -gt 0 ]]; then
    section "기타 (미분류)"
    for key in $(echo "${!VARS[@]}" | tr ' ' '\n' | sort); do
      echo "${key}=${VARS[$key]}"
    done
  fi

  echo ""
} > /tmp/heimdex-env-reformatted

if [[ "$OUTPUT" == "-i" ]]; then
  cp "$INPUT" "${INPUT}.bak.$(date +%Y%m%d%H%M%S)"
  cp /tmp/heimdex-env-reformatted "$INPUT"
  echo "Done. Backup: ${INPUT}.bak.$(date +%Y%m%d%H%M%S -d '-1 sec')" >&2
elif [[ -n "$OUTPUT" ]]; then
  cp /tmp/heimdex-env-reformatted "$OUTPUT"
  echo "Done. Output: $OUTPUT" >&2
else
  cat /tmp/heimdex-env-reformatted
fi

rm -f /tmp/heimdex-env-reformatted
