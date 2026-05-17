#!/usr/bin/env bash
set -euo pipefail

MODEL_DIR="${MODEL_DIR:-/models}"
LLM_URL="https://huggingface.co/bartowski/Qwen2-VL-2B-Instruct-GGUF/resolve/main/Qwen2-VL-2B-Instruct-Q4_K_M.gguf"
LLM_SHA256="SKIP"
LLM_FILE="$MODEL_DIR/Qwen2-VL-2B-Instruct-Q4_K_M.gguf"

MMPROJ_URL="https://huggingface.co/bartowski/Qwen2-VL-2B-Instruct-GGUF/resolve/main/mmproj-Qwen2-VL-2B-Instruct-f16.gguf"
MMPROJ_SHA256="SKIP"
MMPROJ_FILE="$MODEL_DIR/mmproj-Qwen2-VL-2B-Instruct-f16.gguf"

download_and_verify() {
    local url="$1" file="$2" expected_sha="$3"
    local min_size=1000000
    if [[ -f "$file" ]]; then
        local fsize
        fsize=$(stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null || echo 0)
        if [[ "$expected_sha" == "SKIP" && "$fsize" -gt "$min_size" ]]; then
            echo "✓ $(basename "$file") already present ($(numfmt --to=iec "$fsize" 2>/dev/null || echo "${fsize}B"))"
            return 0
        elif [[ "$expected_sha" != "SKIP" ]]; then
            actual=$(sha256sum "$file" | awk '{print $1}')
            if [[ "$actual" == "$expected_sha" ]]; then
                echo "✓ $(basename "$file") already present and verified"
                return 0
            fi
        fi
        echo "⚠ $(basename "$file") invalid or too small, re-downloading..."
        rm -f "$file"
    fi
    echo "⬇ Downloading $(basename "$file")..."
    curl -L --retry 3 --retry-delay 5 -o "$file" "$url"
    local fsize
    fsize=$(stat -c%s "$file" 2>/dev/null || stat -f%z "$file" 2>/dev/null || echo 0)
    if [[ "$fsize" -lt "$min_size" ]]; then
        echo "ERROR: Downloaded file too small (${fsize} bytes) for $(basename "$file")"
        rm -f "$file"
        exit 1
    fi
    if [[ "$expected_sha" != "SKIP" ]]; then
        actual=$(sha256sum "$file" | awk '{print $1}')
        if [[ "$actual" != "$expected_sha" ]]; then
            echo "ERROR: SHA256 mismatch for $(basename "$file")"
            echo "  Expected: $expected_sha"
            echo "  Got:      $actual"
            rm -f "$file"
            exit 1
        fi
    fi
    echo "✓ $(basename "$file") downloaded ($(numfmt --to=iec "$fsize" 2>/dev/null || echo "${fsize}B"))"
}

mkdir -p "$MODEL_DIR"
download_and_verify "$LLM_URL" "$LLM_FILE" "$LLM_SHA256"
download_and_verify "$MMPROJ_URL" "$MMPROJ_FILE" "$MMPROJ_SHA256"
echo "All models ready."
