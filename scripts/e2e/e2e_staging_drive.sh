#!/usr/bin/env bash
set -uo pipefail

EC2_HOST=ec2-user@3.34.75.63
SSH_KEY=~/.ssh/heimdex-staging.pem
API_URL=http://localhost:8000
OPENSEARCH_URL=http://localhost:9200
INDEX=heimdex_scenes_v1
ORG_ID=4d20264c-c440-4d69-8613-7d7558ea386b
DRIVE_KEY=0e95c84cdb03c6219124cdfdda3071d055d33981fd60c3c994692da519cb5d7d
PUBLIC_URL=https://devorg.app.heimdexdemo.dev

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

PASS=0
FAIL=0
TOTAL=0

METRIC_SCENES="n/a"
METRIC_VIDEOS="n/a"
METRIC_GDRIVE_PCT="n/a"
METRIC_TRANSCRIPT_PCT="n/a"
METRIC_EMBEDDING_PCT="n/a"
METRIC_INDEXED_FILES="n/a"
METRIC_FULLY_ENRICHED="n/a"
METRIC_LAST_SYNC_SEC="n/a"
METRIC_SOURCE_BREAKDOWN="n/a"
METRIC_SEARCH_TOTAL_HITS=0

LAST_OUT=""

ssh_cmd() {
  ssh -i "$SSH_KEY" -o StrictHostKeyChecking=no -o ConnectTimeout=10 "$EC2_HOST" "$@"
}

run_ssh() {
  local cmd="$1"
  LAST_OUT="$(ssh_cmd "$cmd" 2>&1)"
  return $?
}

run_ssh_stdin() {
  local cmd="$1"
  local payload="$2"
  LAST_OUT="$(printf '%s' "$payload" | ssh_cmd "$cmd" 2>&1)"
  return $?
}

record() {
  local id="$1" desc="$2" result="$3" detail="${4:-}"
  TOTAL=$((TOTAL + 1))
  if [ "$result" -eq 0 ]; then
    PASS=$((PASS + 1))
    printf "  ${GREEN}[PASS]${NC} %s: %s" "$id" "$desc"
  else
    FAIL=$((FAIL + 1))
    printf "  ${RED}[FAIL]${NC} %s: %s" "$id" "$desc"
  fi
  [ -n "$detail" ] && printf " - %s" "$detail"
  printf "\n"
}

phase() {
  echo ""
  printf "${CYAN}== %s ==${NC}\n" "$1"
}

is_int() {
  [[ "$1" =~ ^[0-9]+$ ]]
}

sanitize_detail() {
  local raw="$1"
  raw="${raw//$'\n'/ }"
  printf '%s' "${raw:0:220}"
}

json_env() {
  local py="$1"
  local data="$2"
  JSON_INPUT="$data" python3 -c "$py" 2>/dev/null
}

os_search() {
  local payload="$1"
  run_ssh_stdin "curl -sS -m 30 '$OPENSEARCH_URL/$INDEX/_search' -H 'Content-Type: application/json' --data-binary @-" "$payload"
}

postgres_query() {
  local sql="$1"
  run_ssh "docker exec heimdex-postgres psql -U heimdex -d heimdex -t -A -c \"$sql\""
}

payload_count_all='{"size":0,"track_total_hits":true,"query":{"match_all":{}}}'
payload_unique_videos='{"size":0,"aggs":{"unique_videos":{"cardinality":{"field":"video_id"}}}}'
payload_exists_transcript='{"size":0,"track_total_hits":true,"query":{"exists":{"field":"transcript_norm"}}}'
payload_exists_embedding='{"size":0,"track_total_hits":true,"query":{"exists":{"field":"embedding_vector"}}}'
payload_source_breakdown='{"size":0,"track_total_hits":true,"aggs":{"unique_videos":{"cardinality":{"field":"video_id"}},"source_type":{"terms":{"field":"source_type","size":10}}}}'
payload_sample_video='{"size":0,"aggs":{"sample_video":{"terms":{"field":"video_id","size":1}}}}'

echo "Heimdex Staging Drive E2E"
echo "Target: $EC2_HOST"

phase "Phase 1 - Environment Health"

if run_ssh "curl -sS -m 20 '$API_URL/health'"; then
  h1_ok="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); print(1 if d.get("status")=="ok" and d.get("environment")=="staging" and d.get("embedding_mode")=="real" else 0)' "$LAST_OUT")"
  h1_detail="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); print(f"status={d.get(\"status\")} env={d.get(\"environment\")} embedding={d.get(\"embedding_mode\")}")' "$LAST_OUT")"
  [ "$h1_ok" = "1" ] && record "H1" "API /health is staging+real" 0 "$h1_detail" || record "H1" "API /health is staging+real" 1 "${h1_detail:-invalid json}"
else
  record "H1" "API /health is staging+real" 1 "ssh/curl failed: $(sanitize_detail "$LAST_OUT")"
fi

if run_ssh "docker ps --filter name=heimdex-drive-worker --format '{{.Status}}'"; then
  status_line="$(printf '%s' "$LAST_OUT" | head -n 1)"
  if [[ -n "$status_line" && "$status_line" == Up* ]]; then
    record "H2" "drive-worker container running" 0 "$status_line"
  else
    record "H2" "drive-worker container running" 1 "status='$status_line'"
  fi
else
  record "H2" "drive-worker container running" 1 "docker ps failed: $(sanitize_detail "$LAST_OUT")"
fi

if run_ssh "curl -sS -m 20 '$OPENSEARCH_URL/_cluster/health'"; then
  h3_status="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); print(d.get("status",""))' "$LAST_OUT")"
  if [ "$h3_status" = "green" ] || [ "$h3_status" = "yellow" ]; then
    record "H3" "OpenSearch cluster health green/yellow" 0 "cluster_status=$h3_status"
  else
    record "H3" "OpenSearch cluster health green/yellow" 1 "cluster_status=${h3_status:-unknown}"
  fi
else
  record "H3" "OpenSearch cluster health green/yellow" 1 "opensearch failed: $(sanitize_detail "$LAST_OUT")"
fi

if postgres_query "SELECT 1;"; then
  pg_val="$(printf '%s' "$LAST_OUT" | tr -d '[:space:]')"
  [ "$pg_val" = "1" ] && record "H4" "Postgres reachable (SELECT 1)" 0 "value=1" || record "H4" "Postgres reachable (SELECT 1)" 1 "value='$pg_val'"
else
  record "H4" "Postgres reachable (SELECT 1)" 1 "psql failed: $(sanitize_detail "$LAST_OUT")"
fi

if run_ssh "curl -sS -o /dev/null -w '%{http_code}' -m 20 '$PUBLIC_URL/api/health'"; then
  code="$(printf '%s' "$LAST_OUT" | tr -d '[:space:]')"
  [ "$code" = "200" ] && record "H5" "Public health endpoint returns 200" 0 "http=200" || record "H5" "Public health endpoint returns 200" 1 "http=$code"
else
  record "H5" "Public health endpoint returns 200" 1 "public curl failed: $(sanitize_detail "$LAST_OUT")"
fi

phase "Phase 2 - Data Integrity Audit"

if os_search "$payload_count_all"; then
  scenes="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); print(d.get("hits",{}).get("total",{}).get("value",-1))' "$LAST_OUT")"
  METRIC_SCENES="$scenes"
  if is_int "$scenes" && [ "$scenes" -ge 1400 ]; then
    record "D1" "Total scene count >= 1400" 0 "count=$scenes"
  else
    record "D1" "Total scene count >= 1400" 1 "count=$scenes"
  fi
else
  record "D1" "Total scene count >= 1400" 1 "query failed: $(sanitize_detail "$LAST_OUT")"
fi

if os_search "$payload_unique_videos"; then
  videos="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); print(int(d.get("aggregations",{}).get("unique_videos",{}).get("value",0)))' "$LAST_OUT")"
  METRIC_VIDEOS="$videos"
  if is_int "$videos" && [ "$videos" -ge 35 ]; then
    record "D2" "Unique video count >= 35" 0 "unique_videos=$videos"
  else
    record "D2" "Unique video count >= 35" 1 "unique_videos=$videos"
  fi
else
  record "D2" "Unique video count >= 35" 1 "query failed: $(sanitize_detail "$LAST_OUT")"
fi

all_count=-1
gdrive_count=-1
if os_search "$payload_count_all"; then
  all_count="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); print(d.get("hits",{}).get("total",{}).get("value",-1))' "$LAST_OUT")"
fi
payload_gdrive='{"size":0,"track_total_hits":true,"query":{"term":{"source_type":"gdrive"}}}'
if os_search "$payload_gdrive"; then
  gdrive_count="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); print(d.get("hits",{}).get("total",{}).get("value",-1))' "$LAST_OUT")"
fi
if is_int "$all_count" && is_int "$gdrive_count" && [ "$all_count" -gt 0 ]; then
  gdrive_pct="$(python3 - "$gdrive_count" "$all_count" <<'PY'
import sys
num=int(sys.argv[1])
den=int(sys.argv[2])
print(f"{(num/den)*100:.1f}")
PY
)"
  METRIC_GDRIVE_PCT="$gdrive_pct"
  if [ "$gdrive_count" -eq "$all_count" ]; then
    record "D3" "All scenes are source_type=gdrive" 0 "gdrive=$gdrive_count/$all_count ($gdrive_pct%)"
  else
    record "D3" "All scenes are source_type=gdrive" 1 "gdrive=$gdrive_count/$all_count ($gdrive_pct%)"
  fi
else
  record "D3" "All scenes are source_type=gdrive" 1 "counts invalid total=$all_count gdrive=$gdrive_count"
fi

if os_search "$payload_exists_transcript"; then
  transcript_count="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); print(d.get("hits",{}).get("total",{}).get("value",-1))' "$LAST_OUT")"
  if is_int "$transcript_count" && is_int "$METRIC_SCENES" && [ "$METRIC_SCENES" -gt 0 ]; then
    transcript_pct="$(python3 - "$transcript_count" "$METRIC_SCENES" <<'PY'
import sys
num=int(sys.argv[1])
den=int(sys.argv[2])
print(f"{(num/den)*100:.1f}")
PY
)"
    METRIC_TRANSCRIPT_PCT="$transcript_pct"
    [ "$transcript_count" -gt 0 ] && record "D4" "Transcript coverage reported" 0 "transcript=$transcript_count/$METRIC_SCENES ($transcript_pct%)" || record "D4" "Transcript coverage reported" 1 "transcript=$transcript_count/$METRIC_SCENES ($transcript_pct%)"
  else
    record "D4" "Transcript coverage reported" 1 "invalid counts"
  fi
else
  record "D4" "Transcript coverage reported" 1 "query failed: $(sanitize_detail "$LAST_OUT")"
fi

if os_search "$payload_exists_embedding"; then
  embedding_count="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); print(d.get("hits",{}).get("total",{}).get("value",-1))' "$LAST_OUT")"
  if is_int "$embedding_count" && is_int "$METRIC_SCENES" && [ "$METRIC_SCENES" -gt 0 ]; then
    embedding_pct="$(python3 - "$embedding_count" "$METRIC_SCENES" <<'PY'
import sys
num=int(sys.argv[1])
den=int(sys.argv[2])
print(f"{(num/den)*100:.1f}")
PY
)"
    METRIC_EMBEDDING_PCT="$embedding_pct"
    [ "$embedding_count" -gt 0 ] && record "D5" "Embedding coverage reported" 0 "embedding=$embedding_count/$METRIC_SCENES ($embedding_pct%)" || record "D5" "Embedding coverage reported" 1 "embedding=$embedding_count/$METRIC_SCENES ($embedding_pct%)"
  else
    record "D5" "Embedding coverage reported" 1 "invalid counts"
  fi
else
  record "D5" "Embedding coverage reported" 1 "query failed: $(sanitize_detail "$LAST_OUT")"
fi

if postgres_query "SELECT processing_status, COUNT(*) FROM drive_files GROUP BY processing_status ORDER BY processing_status;"; then
  d6_raw="$LAST_OUT"
  indexed_count=0
  while IFS='|' read -r status cnt; do
    [ -z "${status// /}" ] && continue
    if [ "$status" = "indexed" ]; then
      indexed_count="$(printf '%s' "$cnt" | tr -d '[:space:]')"
    fi
  done <<INNER
$d6_raw
INNER
  METRIC_INDEXED_FILES="$indexed_count"
  if is_int "$indexed_count" && [ "$indexed_count" -ge 35 ]; then
    record "D6" "Drive files indexed count >= 35" 0 "indexed=$indexed_count"
  else
    record "D6" "Drive files indexed count >= 35" 1 "indexed=$indexed_count"
  fi
else
  record "D6" "Drive files indexed count >= 35" 1 "psql failed: $(sanitize_detail "$LAST_OUT")"
fi

if postgres_query "SELECT COUNT(*) FROM drive_files WHERE stt_status='done' AND ocr_status='done' AND caption_status='done';"; then
  enriched="$(printf '%s' "$LAST_OUT" | tr -d '[:space:]')"
  METRIC_FULLY_ENRICHED="$enriched"
  if is_int "$enriched" && [ "$enriched" -ge 34 ]; then
    record "D7" "Fully enriched files >= 34" 0 "fully_enriched=$enriched"
  else
    record "D7" "Fully enriched files >= 34" 1 "fully_enriched=$enriched"
  fi
else
  record "D7" "Fully enriched files >= 34" 1 "psql failed: $(sanitize_detail "$LAST_OUT")"
fi

phase "Phase 3 - Search Quality Tests"

SEARCH_IDS=(S1 S2 S3 S4 S5 S6 S7 S8)
SEARCH_QUERIES=("라이브커머스" "Samsung Galaxy" "뷰티 화장품" "오설록" "VFX" "롤토체스 강의" "게임" "맛집 추천")
SEARCH_EXPECTED=("글래드코리아/스케치코미디/라이브커머스 마무리" "Samsung Galaxy Note 20 / Galaxy Respect" "뷰티디바이스 / 샴페인핑크" "오설록 AI광고" "GIANTSTEP VFX REEL / SPACE GREEN" "롤토체스 강의" "게임 관련 다수" "을지로맛집")

idx=0
while [ $idx -lt ${#SEARCH_IDS[@]} ]; do
  sid="${SEARCH_IDS[$idx]}"
  query="${SEARCH_QUERIES[$idx]}"
  expected="${SEARCH_EXPECTED[$idx]}"
  payload="$(python3 - "$query" <<'PY'
import json
import sys
q = sys.argv[1]
print(json.dumps({
  "size": 3,
  "query": {
    "bool": {
      "should": [
        {"match": {"transcript_norm": {"query": q}}},
        {"match": {"video_title.nori": {"query": q, "boost": 1.5}}}
      ],
      "minimum_should_match": 1
    }
  }
}, ensure_ascii=False))
PY
)"

  if os_search "$payload"; then
    total_hits="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); print(d.get("hits",{}).get("total",{}).get("value",0))' "$LAST_OUT")"
    top_title="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); h=d.get("hits",{}).get("hits",[]); print(((h[0].get("_source",{}) or {}).get("video_title") if h else ""))' "$LAST_OUT")"
    top_score="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); h=d.get("hits",{}).get("hits",[]); print(h[0].get("_score",0) if h else 0)' "$LAST_OUT")"
    if is_int "$total_hits"; then
      METRIC_SEARCH_TOTAL_HITS=$((METRIC_SEARCH_TOTAL_HITS + total_hits))
    fi
    if is_int "$total_hits" && [ "$total_hits" -gt 0 ]; then
      record "$sid" "BM25 query returns hits" 0 "q='$query' hits=$total_hits top='$top_title' score=$top_score expected=$expected"
    else
      record "$sid" "BM25 query returns hits" 1 "q='$query' hits=$total_hits expected=$expected"
    fi
  else
    record "$sid" "BM25 query returns hits" 1 "q='$query' ssh/query failed: $(sanitize_detail "$LAST_OUT")"
  fi

  idx=$((idx + 1))
done

phase "Phase 4 - API Completeness Tests"

if postgres_query "SELECT COUNT(*) FROM drive_connections WHERE status='active';"; then
  active_conn="$(printf '%s' "$LAST_OUT" | tr -d '[:space:]')"
  if is_int "$active_conn" && [ "$active_conn" -ge 1 ]; then
    record "A1" "Active drive connection exists" 0 "active_connections=$active_conn"
  else
    record "A1" "Active drive connection exists" 1 "active_connections=$active_conn"
  fi
else
  record "A1" "Active drive connection exists" 1 "psql failed: $(sanitize_detail "$LAST_OUT")"
fi

if postgres_query "SELECT COALESCE(EXTRACT(EPOCH FROM (NOW() - MAX(last_sync_at))), 999999)::int FROM drive_connections WHERE status='active';"; then
  sync_sec="$(printf '%s' "$LAST_OUT" | tr -d '[:space:]')"
  METRIC_LAST_SYNC_SEC="$sync_sec"
  if is_int "$sync_sec" && [ "$sync_sec" -le 300 ]; then
    record "A2" "Drive last_sync_at within 5 minutes" 0 "lag_seconds=$sync_sec"
  else
    record "A2" "Drive last_sync_at within 5 minutes" 1 "lag_seconds=$sync_sec"
  fi
else
  record "A2" "Drive last_sync_at within 5 minutes" 1 "psql failed: $(sanitize_detail "$LAST_OUT")"
fi

if os_search "$payload_source_breakdown"; then
  a3_ok="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); print(1 if "aggregations" in d else 0)' "$LAST_OUT")"
  a3_total="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); print(d.get("hits",{}).get("total",{}).get("value",0))' "$LAST_OUT")"
  a3_unique="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); print(int(d.get("aggregations",{}).get("unique_videos",{}).get("value",0)))' "$LAST_OUT")"
  a3_breakdown="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); b=d.get("aggregations",{}).get("source_type",{}).get("buckets",[]); parts=[str(x["key"])+":"+str(x["doc_count"]) for x in b]; print(", ".join(parts) if parts else "none")' "$LAST_OUT")"
  METRIC_SOURCE_BREAKDOWN="$a3_breakdown"
  [ "$a3_ok" = "1" ] && record "A3" "Video/scenes/source_type stats available" 0 "videos=$a3_unique scenes=$a3_total source=[$a3_breakdown]" || record "A3" "Video/scenes/source_type stats available" 1 "parse_error"
else
  record "A3" "Video/scenes/source_type stats available" 1 "query failed: $(sanitize_detail "$LAST_OUT")"
fi

sample_video=""
sample_count=0
if os_search "$payload_sample_video"; then
  sample_video="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); b=d.get("aggregations",{}).get("sample_video",{}).get("buckets",[]); print(b[0].get("key","") if b else "")' "$LAST_OUT")"
  sample_count="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); b=d.get("aggregations",{}).get("sample_video",{}).get("buckets",[]); print(b[0].get("doc_count",0) if b else 0)' "$LAST_OUT")"
fi

if [ -n "$sample_video" ]; then
  payload_detail="$(python3 - "$sample_video" <<'PY'
import json
import sys
v = sys.argv[1]
print(json.dumps({
  "size": 1,
  "query": {"term": {"video_id": v}},
  "_source": ["video_title", "start_ms", "end_ms", "transcript_norm"]
}))
PY
)"
  if os_search "$payload_detail"; then
    a4_ok="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); h=d.get("hits",{}).get("hits",[]); s=(h[0].get("_source",{}) if h else {}); req=["video_title","start_ms","end_ms"]; print(1 if h and all(s.get(k) not in (None, "") for k in req) else 0)' "$LAST_OUT")"
    a4_missing="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); h=d.get("hits",{}).get("hits",[]); s=(h[0].get("_source",{}) if h else {}); req=["video_title","start_ms","end_ms"]; opt=["transcript_norm"]; m=[k for k in req if s.get(k) in (None, "")]; o=[k for k in opt if s.get(k) in (None, "")]; print("missing=" + (",".join(m) if m else "none") + (" (optional_empty=" + ",".join(o) + ")" if o else ""))' "$LAST_OUT")"
    if [ "$a4_ok" = "1" ] && is_int "$sample_count" && [ "$sample_count" -ge 1 ]; then
      record "A4" "Sample video has valid scene fields" 0 "video_id=$sample_video scenes=$sample_count $a4_missing"
    else
      record "A4" "Sample video has valid scene fields" 1 "video_id=$sample_video scenes=$sample_count $a4_missing"
    fi
  else
    record "A4" "Sample video has valid scene fields" 1 "detail query failed: $(sanitize_detail "$LAST_OUT")"
  fi
else
  record "A4" "Sample video has valid scene fields" 1 "no sample video found"
fi

if run_ssh "curl -sS -m 20 '$OPENSEARCH_URL/$INDEX/_mapping'"; then
  knn_dim="$(json_env 'import os,json
def f(o):
  if isinstance(o,dict):
    if o.get("type")=="knn_vector" and "dimension" in o: return o.get("dimension")
    for v in o.values():
      r=f(v)
      if r is not None: return r
  elif isinstance(o,list):
    for v in o:
      r=f(v)
      if r is not None: return r
  return None
d=json.loads(os.environ["JSON_INPUT"])
r=f(d)
print(r if r is not None else -1)' "$LAST_OUT")"
  if is_int "$knn_dim" && [ "$knn_dim" -gt 0 ]; then
    payload_knn="$(python3 - "$knn_dim" <<'PY'
import json
import random
import sys
dim = int(sys.argv[1])
vec = [round(random.uniform(-1, 1), 6) for _ in range(dim)]
print(json.dumps({
  "size": 1,
  "query": {
    "knn": {
      "embedding_vector": {
        "vector": vec,
        "k": 1
      }
    }
  }
}))
PY
)"
    if os_search "$payload_knn"; then
      a5_ok="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); print(0 if "error" in d else 1)' "$LAST_OUT")"
      a5_detail="$(json_env 'import os,json; d=json.loads(os.environ["JSON_INPUT"]); print(str(d.get("error"))[:140] if "error" in d else f"hits={d.get(\"hits\",{}).get(\"total\",{}).get(\"value\",0)}")' "$LAST_OUT")"
      [ "$a5_ok" = "1" ] && record "A5" "kNN search endpoint functional" 0 "dim=$knn_dim $a5_detail" || record "A5" "kNN search endpoint functional" 1 "dim=$knn_dim $a5_detail"
    else
      record "A5" "kNN search endpoint functional" 1 "query failed: $(sanitize_detail "$LAST_OUT")"
    fi
  else
    record "A5" "kNN search endpoint functional" 1 "invalid knn dimension=$knn_dim"
  fi
else
  record "A5" "kNN search endpoint functional" 1 "mapping query failed: $(sanitize_detail "$LAST_OUT")"
fi

if run_ssh "docker logs heimdex-drive-worker --tail 200 2>&1 | grep -c 'discover_connection_complete'"; then
  poll_count="$(printf '%s' "$LAST_OUT" | tr -d '[:space:]')"
  if is_int "$poll_count" && [ "$poll_count" -gt 0 ]; then
    record "A6" "Drive worker polling activity detected" 0 "discover_connection_complete=$poll_count"
  else
    record "A6" "Drive worker polling activity detected" 1 "discover_connection_complete=$poll_count"
  fi
else
  record "A6" "Drive worker polling activity detected" 1 "docker logs failed: $(sanitize_detail "$LAST_OUT")"
fi

pass_rate="$(python3 - "$PASS" "$TOTAL" <<'PY'
import sys
p=int(sys.argv[1])
t=int(sys.argv[2])
print(f"{(p/t)*100:.1f}" if t else "0.0")
PY
)"

echo ""
echo "======================================"
if [ "$FAIL" -eq 0 ]; then
  printf "  ${GREEN}ALL PASSED${NC}: %d/%d (%s%%)\n" "$PASS" "$TOTAL" "$pass_rate"
else
  printf "  ${RED}%d FAILED${NC}: %d/%d passed (%s%%)\n" "$FAIL" "$PASS" "$TOTAL" "$pass_rate"
fi
echo "======================================"
printf "Scenes=%s, UniqueVideos=%s, GDrive%%=%s, Transcript%%=%s, Embedding%%=%s\n" \
  "$METRIC_SCENES" "$METRIC_VIDEOS" "$METRIC_GDRIVE_PCT" "$METRIC_TRANSCRIPT_PCT" "$METRIC_EMBEDDING_PCT"
printf "IndexedFiles=%s, FullyEnriched=%s, LastSyncLagSec=%s\n" \
  "$METRIC_INDEXED_FILES" "$METRIC_FULLY_ENRICHED" "$METRIC_LAST_SYNC_SEC"
printf "SourceBreakdown=[%s], SearchTotalHits=%s\n" \
  "$METRIC_SOURCE_BREAKDOWN" "$METRIC_SEARCH_TOTAL_HITS"

echo ""
exit "$FAIL"
