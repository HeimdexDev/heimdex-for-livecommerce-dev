#!/usr/bin/env bash
set -euo pipefail

/usr/local/bin/download-models.sh

LLAMA_MLOCK_FLAG=""
if [[ "${LLAMA_MLOCK:-false}" == "true" ]]; then
    LLAMA_MLOCK_FLAG="--mlock"
fi

LLAMA_API_KEY_FLAG=""
if [[ -n "${LLAMA_API_KEY:-}" ]]; then
    LLAMA_API_KEY_FLAG="--api-key ${LLAMA_API_KEY}"
fi

echo "Starting llama-server (threads=${LLAMA_THREADS:-2}, mlock=${LLAMA_MLOCK:-false})..."

exec llama-server \
    --model /models/Qwen2-VL-2B-Instruct-Q4_K_M.gguf \
    --mmproj /models/mmproj-Qwen2-VL-2B-Instruct-f16.gguf \
    --host 0.0.0.0 \
    --port 8089 \
    --ctx-size 4096 \
    --parallel 1 \
    --batch-size 1024 \
    --n-predict 200 \
    --threads "${LLAMA_THREADS:-2}" \
    $LLAMA_MLOCK_FLAG \
    $LLAMA_API_KEY_FLAG
