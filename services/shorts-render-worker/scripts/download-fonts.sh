#!/usr/bin/env bash
# Download Korean-compatible fonts for the shorts render worker.
# Run once, commit TTF files to services/shorts-render-worker/fonts/.
# All fonts are OFL 1.1 licensed.
#
# Files are renamed to .ttf to match resolve_font_path() in heimdex-media-contracts.
# ffmpeg drawtext works with both OTF and TTF regardless of extension.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FONTS_DIR="${SCRIPT_DIR}/../fonts"
mkdir -p "$FONTS_DIR"

echo "Downloading Noto Sans KR (OFL 1.1)..."
curl -fsSL -o "$FONTS_DIR/NotoSansKR-Regular.ttf" \
    "https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/KR/NotoSansKR-Regular.otf"
curl -fsSL -o "$FONTS_DIR/NotoSansKR-Bold.ttf" \
    "https://github.com/notofonts/noto-cjk/raw/main/Sans/SubsetOTF/KR/NotoSansKR-Bold.otf"

echo "Downloading Pretendard (OFL 1.1)..."
PRETENDARD_VERSION="v1.3.9"
curl -fsSL -o "$FONTS_DIR/Pretendard-Regular.ttf" \
    "https://github.com/orioncactus/pretendard/raw/${PRETENDARD_VERSION}/packages/pretendard/dist/public/static/Pretendard-Regular.otf"
curl -fsSL -o "$FONTS_DIR/Pretendard-Bold.ttf" \
    "https://github.com/orioncactus/pretendard/raw/${PRETENDARD_VERSION}/packages/pretendard/dist/public/static/Pretendard-Bold.otf"

echo "Downloaded fonts:"
ls -lh "$FONTS_DIR"/*.ttf
echo "Done."
