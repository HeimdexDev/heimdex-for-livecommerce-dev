#!/bin/bash
# ============================================
# EC2 .env → SSM Parameter Store 업로드
# EC2 인스턴스에서 직접 실행
#
# Usage:
#   ./upload-ssm-from-env.sh <ssm-prefix> [env-file]
#
# Examples:
#   ./upload-ssm-from-env.sh /heimdex/prod/tenants/livenow
#   ./upload-ssm-from-env.sh /heimdex/staging /opt/heimdex/.env
#   ./upload-ssm-from-env.sh /heimdex/prod/tenants/ebs
# ============================================

set -euo pipefail

SSM_PREFIX="${1:?Usage: $0 <ssm-prefix> [env-file]}"
ENV_FILE="${2:-/opt/heimdex/.env}"
REGION="ap-northeast-2"

PARAMS=(
  # Secrets
  DATABASE_URL
  DATABASE_URL_SYNC
  JWT_SECRET_KEY
  DEVICE_SECRET_PEPPER
  OPENAI_API_KEY
  AGENT_API_KEY
  AIRCLOUD_API_KEY
  DRIVE_INTERNAL_API_KEY
  DRIVE_SA_ENCRYPTION_KEY
  GOOGLE_OAUTH_CLIENT_ID
  GOOGLE_OAUTH_CLIENT_SECRET
  MINIO_ACCESS_KEY
  MINIO_SECRET_KEY
  HF_ACCESS_TOKEN

  # Service URLs
  OPENSEARCH_URL
  RERANKER_SERVICE_URL
  GOOGLE_OAUTH_REDIRECT_URI
  SQS_PROCESSING_QUEUE_URL
  SQS_CAPTION_QUEUE_URL
  SQS_STT_QUEUE_URL
  SQS_OCR_QUEUE_URL
  SQS_TRANSCODE_QUEUE_URL
  SQS_FACE_QUEUE_URL
  SQS_VISUAL_EMBED_QUEUE_URL
  SQS_EXPORT_QUEUE_URL
  SQS_SHORTS_RENDER_QUEUE_URL
  SQS_BLUR_QUEUE_URL
  SQS_PRODUCT_ENUMERATE_QUEUE_URL
  SQS_PRODUCT_TRACK_QUEUE_URL
  AIRCLOUD_ENDPOINT_TRANSCODE
  AIRCLOUD_ENDPOINT_CAPTION
  AIRCLOUD_ENDPOINT_STT
  AIRCLOUD_ENDPOINT_OCR
  AIRCLOUD_ENDPOINT_FACE
  AIRCLOUD_ENDPOINT_VISUAL_EMBED
  AIRCLOUD_ENDPOINT_BLUR
  AIRCLOUD_ENDPOINT_PRODUCT_ENUMERATE
  AIRCLOUD_ENDPOINT_PRODUCT_TRACK
)

if [ ! -f "$ENV_FILE" ]; then
  echo "ERROR: $ENV_FILE not found"
  exit 1
fi

echo "Source:  $ENV_FILE"
echo "Target:  $SSM_PREFIX/*"
echo "Region:  $REGION"
echo "Params:  ${#PARAMS[@]}"
echo "---"

OK=0
SKIP=0
FAIL=0

for p in "${PARAMS[@]}"; do
  val=$(grep "^${p}=" "$ENV_FILE" | head -1 | cut -d'=' -f2-)
  if [ -z "$val" ]; then
    echo "SKIP: $p (empty or not found)"
    ((SKIP++))
    continue
  fi

  if aws ssm put-parameter \
    --name "${SSM_PREFIX}/${p}" \
    --value "$val" \
    --type SecureString \
    --overwrite \
    --region "$REGION" \
    --no-cli-pager > /dev/null 2>&1; then
    echo "  OK: $p"
    ((OK++))
  else
    echo "FAIL: $p"
    ((FAIL++))
  fi
done

echo "---"
echo "Done: OK=$OK  SKIP=$SKIP  FAIL=$FAIL"
