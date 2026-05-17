#!/usr/bin/env bash
set -e
HEALTH_URL="http://localhost:8089/health"
if [ -n "${LLAMA_API_KEY:-}" ]; then
    curl -sf -H "Authorization: Bearer $LLAMA_API_KEY" "$HEALTH_URL" | grep -q '"status":"ok"'
else
    curl -sf "$HEALTH_URL" | grep -q '"status":"ok"'
fi
