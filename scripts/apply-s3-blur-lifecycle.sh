#!/usr/bin/env bash
# Apply S3 lifecycle rules for the v0.10 blur layer subsystem.
#
# Two rules — both scoped by prefix so they never touch non-blur
# objects in the shared drive bucket:
#
#   1. ``blurred/*/masks/*`` — lossless FFV1 mask videos uploaded by
#      drive-blur-worker. These are retained long enough to support
#      re-exporting a done blur job with a different category subset
#      without re-running OWLv2. Moved to Standard-IA after 30 days to
#      drop storage cost by ~40%, then expired after 180 days.
#
#   2. ``blur_exports/*`` — composed ProRes 4444 layer ``.mov`` files.
#      These are ephemeral downloads — the customer grabs one, pulls
#      it into their NLE, and never asks for it again. Expire after
#      7 days so they never accumulate.
#
# This script is idempotent. It pulls the existing lifecycle config,
# merges in the two blur rules (replacing any prior rules with the
# same IDs), and puts it back. Safe to re-run after an operator has
# added unrelated lifecycle rules — they're preserved.
#
# Usage:
#   ./scripts/apply-s3-blur-lifecycle.sh <bucket> [--apply]
#
# Without ``--apply`` it prints the proposed configuration and exits
# without touching S3. Pass ``--apply`` to commit.
#
# Requires: awscli v2, jq.

set -euo pipefail

BUCKET="${1:-}"
APPLY="${2:-}"

if [[ -z "$BUCKET" ]]; then
  echo "usage: $0 <bucket> [--apply]" >&2
  exit 1
fi

if ! command -v aws >/dev/null 2>&1; then
  echo "ERROR: aws CLI is required" >&2
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required" >&2
  exit 1
fi

BLUR_RULES=$(cat <<'JSON'
[
  {
    "ID": "heimdex-blur-masks-retention",
    "Status": "Enabled",
    "Filter": { "Prefix": "blurred/" },
    "Transitions": [
      { "Days": 30, "StorageClass": "STANDARD_IA" }
    ],
    "Expiration": { "Days": 180 },
    "NoncurrentVersionExpiration": { "NoncurrentDays": 7 },
    "AbortIncompleteMultipartUpload": { "DaysAfterInitiation": 3 }
  },
  {
    "ID": "heimdex-blur-exports-expiry",
    "Status": "Enabled",
    "Filter": { "Prefix": "blur_exports/" },
    "Expiration": { "Days": 7 },
    "NoncurrentVersionExpiration": { "NoncurrentDays": 1 },
    "AbortIncompleteMultipartUpload": { "DaysAfterInitiation": 1 }
  }
]
JSON
)

# Fetch existing lifecycle (if any) so we preserve unrelated rules.
EXISTING=$(aws s3api get-bucket-lifecycle-configuration --bucket "$BUCKET" 2>/dev/null || echo '{"Rules":[]}')

# Drop any pre-existing rules with our IDs (makes the script idempotent),
# then append the two blur rules. The ``as $kept | ...`` binding is what
# keeps jq's parser happy — chaining ``map(...)`` directly into ``+``
# inside a parenthesized group trips a precedence bug on older jq.
MERGED=$(jq -n \
  --argjson existing "$EXISTING" \
  --argjson blur "$BLUR_RULES" \
  '($existing.Rules // [])
    | map(select(.ID != "heimdex-blur-masks-retention" and .ID != "heimdex-blur-exports-expiry"))
    | . as $kept
    | { Rules: ($kept + $blur) }')

echo "== Proposed lifecycle configuration for bucket: $BUCKET =="
echo "$MERGED" | jq .
echo

if [[ "$APPLY" != "--apply" ]]; then
  echo "(dry-run — pass --apply to commit)"
  exit 0
fi

TMP=$(mktemp)
trap 'rm -f "$TMP"' EXIT
echo "$MERGED" > "$TMP"

aws s3api put-bucket-lifecycle-configuration \
  --bucket "$BUCKET" \
  --lifecycle-configuration "file://$TMP"

echo "applied lifecycle rules to $BUCKET"
