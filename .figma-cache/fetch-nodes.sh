#!/usr/bin/env bash
# Figma REST API로 P3 디자인 노드 13개를 fetch해서 .figma-cache/ 에 저장.
# Claude 토큰 소모 0 — 본인 PAT만 있으면 됨.
#
# 사용법:
#   1) https://www.figma.com/developers/api#access-tokens 에서 PAT 발급 (이름: heimdex-p3-cache)
#   2) export FIGMA_TOKEN="figd_xxxxx"
#   3) bash .figma-cache/fetch-nodes.sh
#
# 옵션:
#   IMAGES=1 bash .figma-cache/fetch-nodes.sh   # PNG 렌더 URL도 함께 fetch
#   SVG=1    bash .figma-cache/fetch-nodes.sh   # SVG 렌더 URL도 함께 fetch
#   FORCE=1  bash .figma-cache/fetch-nodes.sh   # 기존 *.api.json 덮어쓰기

set -euo pipefail

: "${FIGMA_TOKEN:?FIGMA_TOKEN 환경변수가 필요합니다. https://www.figma.com/developers/api#access-tokens 에서 발급 후 export FIGMA_TOKEN=figd_xxx}"

# 의존성 확인
for cmd in curl jq; do
  command -v "$cmd" >/dev/null 2>&1 || { echo "ERR: '$cmd' 필요. apt install curl jq" >&2; exit 1; }
done

FILE_KEY="PYDMMAvFq7PmhjyVTftiU6"
OUTDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API_BASE="https://api.figma.com/v1"

# 노드 ID → 슬러그 매핑 (Phase 별 정렬)
declare -A NODES=(
  ["1713:270773"]="phase1_video-detail-overview"
  ["1713:288216"]="phase2_wizard-criteria"
  ["1713:288103"]="phase2_wizard-indexing"
  ["1713:288149"]="phase2_wizard-product-single"
  ["1713:288182"]="phase2_wizard-product-multi"
  ["1713:288042"]="phase3_wizard-result"
  ["1602:36895"]="phase3_cancel-dialog"
  ["1713:287987"]="phase4_saved-shorts"
  ["1713:271669"]="phase5_editor-1"
  ["1713:274802"]="phase5_editor-2"
  ["1713:275432"]="phase5_editor-3"
  ["1713:275817"]="phase5_editor-4"
  ["1713:275105"]="phase5_editor-5"
)

# 콤마 구분 ID 리스트 (API 인자용)
IDS=""
for nid in "${!NODES[@]}"; do
  IDS+="${IDS:+,}${nid}"
done

echo "==> Fetching ${#NODES[@]} nodes from Figma REST API..."
echo "    fileKey: $FILE_KEY"
echo "    outdir : $OUTDIR"

# 1) /v1/files/{fileKey}/nodes — 전체 노드 트리 + 스타일 + 텍스트
RAW="${OUTDIR}/_all-nodes-raw.json"
echo "==> [1/3] GET ${API_BASE}/files/${FILE_KEY}/nodes?ids=..."
http_code=$(curl -sS -o "$RAW" -w "%{http_code}" \
  -H "X-Figma-Token: $FIGMA_TOKEN" \
  "${API_BASE}/files/${FILE_KEY}/nodes?ids=${IDS}")

if [[ "$http_code" != "200" ]]; then
  echo "ERR: Figma API responded $http_code" >&2
  cat "$RAW" >&2
  exit 1
fi

# 2) per-node JSON split
echo "==> [2/3] Splitting per-node JSON..."
for nid in "${!NODES[@]}"; do
  slug="${NODES[$nid]}"
  filename="${nid//:/-}_${slug}.api.json"
  outpath="${OUTDIR}/${filename}"
  if [[ -f "$outpath" && -z "${FORCE:-}" ]]; then
    echo "    skip ${filename} (FORCE=1 to overwrite)"
    continue
  fi
  # jq의 키 lookup은 nodeId 그대로 ("1713:270773") 사용
  if jq -e --arg id "$nid" '.nodes[$id]' "$RAW" >/dev/null 2>&1; then
    jq --arg id "$nid" '.nodes[$id]' "$RAW" > "$outpath"
    size=$(wc -c < "$outpath")
    echo "    ✓ ${filename} (${size} bytes)"
  else
    echo "    ✗ ${filename} (노드 ID가 응답에 없음 — 권한/오타 확인)" >&2
  fi
done

# 3) (선택) PNG/SVG 렌더 URL fetch
if [[ -n "${IMAGES:-}" ]]; then
  echo "==> [3/3] PNG 렌더 URL fetch..."
  curl -sS -H "X-Figma-Token: $FIGMA_TOKEN" \
    "${API_BASE}/images/${FILE_KEY}?ids=${IDS}&format=png&scale=2" \
    > "${OUTDIR}/_images-png.json"
  echo "    ✓ _images-png.json"
fi

if [[ -n "${SVG:-}" ]]; then
  echo "==> [3/3] SVG 렌더 URL fetch..."
  curl -sS -H "X-Figma-Token: $FIGMA_TOKEN" \
    "${API_BASE}/images/${FILE_KEY}?ids=${IDS}&format=svg" \
    > "${OUTDIR}/_images-svg.json"
  echo "    ✓ _images-svg.json"
fi

echo "==> Done. JSON 파일은 $OUTDIR 에 저장됨."
echo "    Claude 세션에서 Read 도구로 필요한 부분만 읽어 사용 (토큰 절약)."
