# Shorts & Export Specification: Proxy-First Google Drive

**Date**: 2026-02-19
**Status**: Proposed
**Reference**: [ARCHITECTURE.md](./ARCHITECTURE.md)

---

## Overview

Heimdex stores only **720p H.264 proxy** videos from Google Drive. Originals stay on Drive. This creates two distinct export tiers:

| Tier | Source | Speed | Accuracy | Use Case |
|------|--------|-------|----------|----------|
| **A — Shorts Preview** | Proxy in S3 | Instant | ±0–2s (GOP-aligned) | In-app preview, scrubbing, social media draft |
| **B — HQ Export** | Original from Drive | Async (minutes) | ±1 frame (re-encode) or ±0–2s (stream-copy) | Premiere Pro, Final Cut, broadcast delivery |

---

## Current State (Validated Against Codebase)

### What Exists Today

| Component | Location | How It Works |
|-----------|----------|-------------|
| **SavedShort model** | `services/api/app/modules/shorts/models.py:12-35` | Postgres bookmark: `id, org_id, user_id, video_id, scene_ids (JSON), title, start_ms, end_ms` |
| **Shorts scorer** | `heimdex-media-contracts/.../shorts/scorer.py:34-69` | `score_scene()` — weighted: keyword_density(0.30), face_presence(0.20), transcript_richness(0.15), tag_diversity(0.15), duration_fitness(0.20) |
| **Candidate selection** | `heimdex-media-contracts/.../shorts/scorer.py:72-104` | `select_shorts_candidates(scenes, target_count=15, min=30s, max=60s)` — pure function, no I/O |
| **Shorts plan API** | `services/api/app/modules/videos/router.py:109-132` | `POST /api/videos/{video_id}/shorts/plan` → fetches scenes from OpenSearch → calls scorer → returns candidates |
| **Saved shorts CRUD** | `services/api/app/modules/shorts/router.py:35-88` | `POST/GET/DELETE /api/shorts` — scoped by org_id + user_id |
| **ExportClip schema** | `heimdex-media-contracts/.../exports/schemas.py:14-35` | `clip_name, video_id, media_path="", media_url="", start_ms, end_ms, scene_id, markers[]` |
| **EDL generator** | `heimdex-media-contracts/.../exports/edl.py:22-57` | `generate_edl(clips, title, frame_rate)` — CMX 3600 format |
| **FCPXML generator** | `heimdex-media-contracts/.../exports/fcpxml.py:43-113` | `generate_fcpxml(clips, project_name, frame_rate)` — FCPXML v1.9 |
| **Agent export handler** | `heimdex-agent/internal/api/export_handler.go:13-104` | `POST /export/premiere` — resolves video_id → local File.Path → generates EDL → writes to disk |
| **Agent clip download** | `services/web/src/lib/agent.ts:85-91` | `getAgentClipUrl()` → `http://127.0.0.1:8787/export/clip?file_id=...&start_ms=...&end_ms=...` |
| **Frontend export flow** | `services/web/src/lib/agent-export.ts:6-34` | `exportToPremiere()` → POST to agent localhost:8787, 30s timeout |
| **Saved shorts page** | `services/web/src/features/shorts/components/SavedShortsPage.tsx` | Multi-select → "클립 다운로드" (agent clip) or "Premiere Pro 내보내기" (agent EDL) |

### Key Observations

1. **`ExportClip.media_url` exists but is unused.** It was designed for remote URLs — exactly what we need for proxy and Drive exports.
2. **All export currently routes through the local agent** (localhost:8787). No server-side export exists.
3. **SavedShort is source-agnostic.** It stores `video_id` as a plain string — works identically for `gd_*` (Drive) and agent video IDs.
4. **Shorts scoring is pure computation.** `select_shorts_candidates()` takes SceneDocuments (from OpenSearch), returns candidates. No file access needed. Works identically for Drive-sourced scenes.
5. **No ffmpeg clip cutting exists in the SaaS codebase.** Agent does clip export via Go. Media-pipelines have ffmpeg for scene detection/keyframes but not clip extraction.

### What This Means

- **Shorts plan generation already works for Drive videos** — no changes needed. Scene data in OpenSearch is source-agnostic.
- **SavedShort CRUD already works for Drive videos** — `video_id` is just a string.
- **Export is the only gap** — agent can't export Drive videos (it doesn't have the files). We need server-side export.

---

## Tier A: Shorts Preview (Proxy-Based)

### Design

For Drive-sourced videos, the proxy in S3 replaces the agent's local file. The frontend detects `source_type="gdrive"` and routes export through the SaaS API instead of the agent.

```
User selects shorts → clicks "Preview" or "Download Clip"
    │
    ├─ source_type == "local" or "removable_disk"
    │   → Agent clip: GET http://127.0.0.1:8787/export/clip?...  (unchanged)
    │
    └─ source_type == "gdrive"
        → SaaS proxy clip: GET /api/drive/clips/{video_id}?start_ms=X&end_ms=Y
            → Worker cuts clip from proxy via ffmpeg stream-copy
            → Returns 302 → presigned S3 URL
```

### Proxy Clip Endpoint

```
GET /api/drive/clips/{video_id}?start_ms={start}&end_ms={end}
Authorization: Bearer {jwt}

Response: 302 → presigned S3 URL to cut clip
Headers:
  Cache-Control: no-store
  Location: https://minio:9000/heimdex-media/{org_id}/exports/...
```

### ffmpeg Command (Stream-Copy from Proxy)

```bash
ffmpeg -hide_banner \
  -ss {START_SECONDS:.5f} \
  -i "{PROXY_PATH}" \
  -t {DURATION_SECONDS:.5f} \
  -c copy \
  -map 0 \
  -avoid_negative_ts make_zero \
  -movflags +faststart \
  -y "{OUTPUT}.mp4"
```

### Accuracy

The proxy is encoded with GOP 48 (2s at 24fps). Stream-copy cuts snap to keyframe boundaries:

| Metric | Value |
|--------|-------|
| Start accuracy | ±0–2,000 ms (snaps to nearest preceding keyframe) |
| End accuracy | ±0–2,000 ms (extends to next keyframe after requested end) |
| Average inaccuracy | ~1 second |
| Clip duration deviation | may be 0–4s longer than requested |
| Quality | Lossless (no re-encode of proxy) |
| Speed | < 2 seconds for any clip length |

### When to Use

- Quick preview of a shorts candidate
- Social media draft (Instagram, TikTok — 720p is fine)
- In-app scrubbing / timeline playback
- Any scenario where ±2s accuracy is acceptable

---

## Tier B: HQ Export (Original from Drive)

### Design

For frame-accurate, original-quality exports (Premiere Pro, Final Cut, broadcast), the system fetches the original from Google Drive asynchronously.

```
User selects shorts → clicks "HQ Export"
    │
    ├─ source_type == "local" or "removable_disk"
    │   → Agent export: POST http://127.0.0.1:8787/export/premiere  (unchanged)
    │
    └─ source_type == "gdrive"
        → SaaS async export:
            POST /api/drive/exports
            Body: { video_id, clips: [{start_ms, end_ms, clip_name}], mode: "fast"|"precise", format: "clip"|"edl"|"fcpxml" }
            Response: 202 { job_id, status: "pending", estimated_time_seconds }
            │
            └─ Poll: GET /api/drive/exports/{job_id}
                → { status: "downloading"|"cutting"|"completed"|"failed", download_url, expires_at }
```

### Two Sub-Modes for HQ Cutting

#### Mode: `fast` (Stream-Copy from Original)

**When to use**: Quick delivery, keyframe-aligned accuracy acceptable.

```bash
ffmpeg -hide_banner \
  -ss {START_SECONDS:.5f} \
  -i "{ORIGINAL_PATH}" \
  -t {DURATION_SECONDS:.5f} \
  -c copy \
  -map 0 \
  -avoid_negative_ts make_zero \
  -movflags +faststart \
  -y "{OUTPUT}.mp4"
```

| Metric | Value |
|--------|-------|
| Start accuracy | ±0–2,000 ms (GOP-dependent, source GOP varies) |
| Quality | Lossless (identical to original) |
| Speed | < 2 seconds for cutting; download is the bottleneck |
| Output size | Same bitrate as original (~8-15 Mbps for 1080p) |

#### Mode: `precise` (Re-Encode for Frame Accuracy)

**When to use**: Premiere Pro assembly, broadcast delivery, frame-accurate cuts.

```bash
ffmpeg -hide_banner \
  -ss {START_SECONDS:.5f} \
  -i "{ORIGINAL_PATH}" \
  -ss 0 \
  -t {DURATION_SECONDS:.5f} \
  -c:v libx264 \
  -profile:v high \
  -preset medium \
  -crf 18 \
  -pix_fmt yuv420p \
  -c:a aac \
  -b:a 192k \
  -movflags +faststart \
  -y "{OUTPUT}.mp4"
```

**The double `-ss` trick**: First `-ss` before `-i` does fast keyframe seek (avoids decoding entire source). Second `-ss 0` after `-i` starts output from the decoded buffer beginning. This gives fast seek AND frame accuracy.

| Metric | Value |
|--------|-------|
| Start accuracy | ±1 frame (~33 ms at 30fps) |
| End accuracy | ±1 frame |
| Quality | Near-lossless (CRF 18, visually identical to original) |
| Speed | ~15-45 seconds for a 30s clip (medium preset) |
| Output size | ~1.5× source bitrate |

**Quota**: `precise` mode is quota-limited because it requires both Drive download bandwidth AND CPU-intensive re-encoding.

### Performance Matrix

For a 30-second clip from a 2-hour 1080p source (8 Mbps, H.264):

| Step | `fast` mode | `precise` mode |
|------|-------------|----------------|
| Download original from Drive (3 GB) | ~30-60s @ 50-100 MB/s | Same |
| ffmpeg cutting | < 2s (stream copy) | 15-45s (re-encode) |
| Upload to S3 | < 1s (30 MB clip) | < 1s |
| **Total** | **~35-65s** | **~50-110s** |

**Note**: If the original was already downloaded for another clip from the same video, the download step is skipped (cached for duration of job batch).

### Smart-Cut (Future Optimization — Not v1)

A hybrid approach that re-encodes only the boundary GOPs and stream-copies the middle:

```
Desired: [5.7s ──────────────── 35.7s]
Step 1: Find next keyframe after 5.7s → 6.0s
Step 2: Re-encode [5.7s → 6.0s]   (0.3s, tiny segment)
Step 3: Stream-copy [6.0s → 34.0s] (lossless bulk)
Step 4: Re-encode [34.0s → 35.7s]  (optional end boundary)
Step 5: Concat all segments
```

This gives frame-accurate cuts with near-lossless quality and near stream-copy speed. **Defer to v2** — adds significant complexity (keyframe probing, concat, edge cases when entire clip fits within one GOP).

---

## Export Format Integration

### How ExportClip.media_url Gets Populated

Currently `ExportClip.media_url` is always `""`. For Drive exports:

| Export Type | `media_path` | `media_url` |
|-------------|-------------|-------------|
| Agent (local) | `/Users/.../video.mp4` (absolute) | `""` (unused) |
| Drive proxy preview | `""` (unused) | Presigned S3 URL to proxy clip |
| Drive HQ fast/precise | `""` (unused) | Presigned S3 URL to HQ clip |

### EDL Generation for Drive Exports

```python
# For Drive exports, EDL references the S3 presigned URL instead of a local path
clips = [
    ExportClip(
        clip_name=short.title or f"shorts_{i:03d}",
        video_id=drive_file.video_id,
        media_url=presigned_clip_url,     # ← S3 URL to exported clip
        media_path="",                     # ← empty for Drive
        start_ms=short.start_ms,
        end_ms=short.end_ms,
        scene_id=short.scene_ids[0],
    )
    for i, short in enumerate(selected_shorts)
]
edl_text = generate_edl(clips, project_name, frame_rate)
```

**Important**: The EDL `AX` comment line currently uses `media_path`:
```
* FROM CLIP NAME: {clip.clip_name}
* COMMENT: SRC={clip.media_path}
```

For Drive exports, we need to check `media_url` as a fallback. This is a **one-line change** in `edl.py`:
```python
src = clip.media_path or clip.media_url
```

Similarly for FCPXML's `<asset>` `src` attribute.

---

## API Design

### New Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| `GET` | `/api/drive/clips/{video_id}` | JWT | Synchronous proxy clip — stream-copy from S3 proxy, returns 302 |
| `POST` | `/api/drive/exports` | JWT | Create async HQ export job |
| `GET` | `/api/drive/exports/{job_id}` | JWT | Poll export job status + download URL |

### `GET /api/drive/clips/{video_id}` — Proxy Clip (Tier A)

```
Query params:
  start_ms: int (required)
  end_ms: int (required)

Response (success): 302 → presigned S3 URL
Response (processing): 202 { "status": "processing", "retry_after_seconds": 5 }
Response (not found): 404

Notes:
- Clip is cut on-demand from the proxy in S3
- Result cached in S3 exports/ for 1 hour (dedup identical requests)
- Cache key: sha256(org_id:video_id:start_ms:end_ms)
- Max clip duration: 300 seconds (5 minutes)
```

### `POST /api/drive/exports` — HQ Export (Tier B)

```json
{
  "video_id": "gd_abc123def456",
  "clips": [
    {
      "clip_name": "제품 소개 하이라이트",
      "start_ms": 5700,
      "end_ms": 35700,
      "scene_id": "gd_abc123def456_scene_003"
    }
  ],
  "mode": "fast",       // "fast" (stream-copy) or "precise" (re-encode)
  "format": "clips",    // "clips" (MP4 files) or "edl" or "fcpxml"
  "frame_rate": 30.0    // only for edl/fcpxml
}

Response: 202
{
  "job_id": "uuid",
  "status": "pending",
  "estimated_time_seconds": 90,
  "clips_count": 1
}
```

### `GET /api/drive/exports/{job_id}` — Poll Status

```json
{
  "job_id": "uuid",
  "status": "completed",       // pending | downloading | cutting | uploading | completed | failed | expired
  "clips": [
    {
      "clip_name": "제품 소개 하이라이트",
      "download_url": "https://minio/...",
      "file_size_bytes": 31457280,
      "duration_ms": 30000,
      "mode": "fast",
      "actual_start_ms": 4000,   // actual start after keyframe alignment (fast mode)
      "actual_end_ms": 36000
    }
  ],
  "edl_url": null,              // populated for format="edl"
  "fcpxml_url": null,           // populated for format="fcpxml"
  "expires_at": "2026-02-20T17:31:00Z",
  "error": null
}
```

---

## Quota & Rate Limiting

### Per-Org Export Quotas

| Quota | Limit | Rationale |
|-------|-------|-----------|
| Proxy clips per hour | 60 | Stream-copy is cheap; limit to prevent S3 write abuse |
| HQ exports per day (fast) | 30 | Each requires Drive download; ~3 GB/export avg |
| HQ exports per day (precise) | 10 | Adds CPU-intensive re-encode on top of download |
| Concurrent HQ downloads per org | 2 | Don't monopolize Drive API quota |
| Max clip duration (proxy) | 300s (5 min) | Prevent full-video downloads via clip endpoint |
| Max clip duration (HQ) | 600s (10 min) | Prevent abuse |
| Export retention | 24h | S3 lifecycle auto-cleanup |

### Enforcement

```python
# Checked at POST /api/drive/exports
async def check_export_quota(org_id: UUID, mode: str) -> bool:
    since_24h = datetime.now(tz=timezone.utc) - timedelta(hours=24)
    count = await export_repo.count_by_org_and_mode(org_id, mode, since=since_24h)
    limit = 30 if mode == "fast" else 10
    return count < limit
```

Return `429 Too Many Requests` with `Retry-After` header when quota exceeded.

---

## Frontend Integration

### Updated Export Flow

The SavedShortsPage needs conditional routing based on `source_type`:

```typescript
// SavedShortsPage.tsx — updated handleClipDownload
const handleClipDownload = useCallback(() => {
  for (const short of selectedShorts) {
    if (short.source_type === "gdrive") {
      // Drive: use SaaS proxy clip endpoint
      const url = `/api/drive/clips/${encodeURIComponent(short.video_id)}`
        + `?start_ms=${short.start_ms}&end_ms=${short.end_ms}`;
      window.open(url, "_blank");
    } else {
      // Local/removable: use agent clip endpoint (unchanged)
      const url = getAgentClipUrl(short.video_id, short.start_ms, short.end_ms, short.title);
      const a = document.createElement("a");
      a.href = url;
      a.download = short.title ?? `clip_${short.video_id}`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
    }
  }
}, [selectedShorts]);
```

### Updated Premiere Export Flow

```typescript
// SavedShortsPage.tsx — updated handlePremiereExport
const handlePremiereExport = useCallback(async (config) => {
  const driveShorts = selectedShorts.filter(s => s.source_type === "gdrive");
  const localShorts = selectedShorts.filter(s => s.source_type !== "gdrive");

  // Local shorts: export via agent (unchanged)
  if (localShorts.length > 0) {
    const clips = localShorts.map(s => ({
      video_id: s.video_id,
      scene_id: s.scene_ids[0],
      clip_name: s.title ?? `shorts_${s.scene_ids.length}_scenes`,
      start_ms: s.start_ms ?? 0,
      end_ms: s.end_ms ?? 0,
    }));
    await exportToPremiere({ ...config, clips });
  }

  // Drive shorts: export via SaaS async job
  if (driveShorts.length > 0) {
    const resp = await fetch("/api/drive/exports", {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({
        video_id: driveShorts[0].video_id,
        clips: driveShorts.map(s => ({
          clip_name: s.title ?? `shorts_${s.scene_ids.length}_scenes`,
          start_ms: s.start_ms ?? 0,
          end_ms: s.end_ms ?? 0,
          scene_id: s.scene_ids[0],
        })),
        mode: "fast",  // or "precise" via UI toggle
        format: "edl",
        frame_rate: config.frameRate,
      }),
    });
    // Show async job status UI...
  }
}, [selectedShorts]);
```

### UI Changes Required

1. **SavedShortsPage**: Add `source_type` to the `SavedShort` interface (fetch from API)
2. **Export menu**: Show "빠른 내보내기 (스트림 복사)" / "정밀 내보내기 (프레임 정확)" toggle for Drive shorts
3. **Export status toast**: Show async job progress for Drive HQ exports (polling)
4. **Quota indicator**: Show remaining daily exports

### Data Gap: `source_type` in SavedShort

**Current**: `SavedShort` doesn't store `source_type`. The frontend needs it for routing.

**Options**:
1. **Add `source_type` column to `saved_shorts` table** — stores at creation time
2. **Infer from `video_id` prefix** — `gd_*` → gdrive, else local/removable
3. **Fetch from OpenSearch** — query source_type for each video_id at render time

**Recommendation**: Option 2 (infer from prefix). Zero migration, zero API change, deterministic. The `gd_` prefix is guaranteed unique to Drive videos by architecture.

```typescript
function inferSourceType(videoId: string): "gdrive" | "local" {
  return videoId.startsWith("gd_") ? "gdrive" : "local";
}
```

---

## Postgres Schema (Export Jobs — from Architecture Doc)

```sql
CREATE TABLE drive_export_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    drive_file_id   UUID NOT NULL REFERENCES drive_files(id),
    video_id        TEXT NOT NULL,
    mode            TEXT NOT NULL DEFAULT 'fast',       -- 'fast' | 'precise'
    format          TEXT NOT NULL DEFAULT 'clips',      -- 'clips' | 'edl' | 'fcpxml'
    frame_rate      REAL NOT NULL DEFAULT 30.0,
    clips_json      JSONB NOT NULL,                     -- [{clip_name, start_ms, end_ms, scene_id}]
    status          TEXT NOT NULL DEFAULT 'pending',
    -- pending → downloading → cutting → uploading → completed | failed | expired
    s3_keys         JSONB,                              -- [{clip_name, s3_key, size_bytes, duration_ms, actual_start_ms, actual_end_ms}]
    edl_s3_key      TEXT,
    fcpxml_s3_key   TEXT,
    error_message   TEXT,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,                        -- created_at + 24h

    CONSTRAINT uq_export_dedup UNIQUE (org_id, user_id, video_id, clips_json, mode)
);

CREATE INDEX ix_drive_export_jobs_status ON drive_export_jobs(status);
CREATE INDEX ix_drive_export_jobs_org_user ON drive_export_jobs(org_id, user_id);
CREATE INDEX ix_drive_export_jobs_expires ON drive_export_jobs(expires_at)
    WHERE status = 'completed';
```

---

## Worker Processing Flow (HQ Export)

```
1. Worker picks pending export job
   SELECT ... WHERE status='pending' FOR UPDATE SKIP LOCKED LIMIT 1

2. Set status='downloading'
   Check if original already cached in /tmp (from another clip of same video)
   If not: download from Drive via manual Range headers (NOT MediaIoBaseDownload)
   Verify MD5

3. Set status='cutting'
   For each clip in clips_json:
     If mode='fast':
       ffmpeg -ss {start} -i original -t {duration} -c copy -avoid_negative_ts make_zero -movflags +faststart output.mp4
     If mode='precise':
       ffmpeg -ss {start} -i original -ss 0 -t {duration} -c:v libx264 -crf 18 -preset medium -movflags +faststart output.mp4

4. Set status='uploading'
   Upload each clip to S3: {org_id}/exports/{job_id}/{clip_name}.mp4
   If format='edl': generate EDL text, upload to S3
   If format='fcpxml': generate FCPXML, upload to S3

5. Set status='completed'
   Set completed_at, expires_at = now + 24h
   Update s3_keys JSON

6. Cleanup
   Do NOT delete original from /tmp yet (other clips from same video may be pending)
   Original cleanup happens via separate cleanup task (after all pending jobs for that video_id finish)
```

### Critical: MediaIoBaseDownload Does Not Support Resume

Research confirmed that `google-api-python-client`'s `MediaIoBaseDownload` **always starts from byte 0** — it has no resume capability ([GitHub Issue #2309](https://github.com/googleapis/google-api-python-client/issues/2309)).

For large video files (1-10 GB), use manual `Range` headers with `google.auth.transport.requests.AuthorizedSession`:

```python
# Resume-safe download pattern
start_byte = dest_path.stat().st_size if dest_path.exists() else 0
with open(dest_path, "ab") as f:
    while start_byte < file_size:
        headers = {"Range": f"bytes={start_byte}-{min(start_byte + 32*1024*1024 - 1, file_size - 1)}"}
        resp = authed_session.get(url, headers=headers, stream=True, timeout=(15, 600))
        for chunk in resp.iter_content(chunk_size=4*1024*1024):
            f.write(chunk)
        f.flush()
        start_byte = dest_path.stat().st_size  # ground truth from disk
```

---

## Testing Plan

### Unit Tests (Mocked)

| Test | What It Verifies |
|------|-----------------|
| `test_proxy_clip_stream_copy_cmd` | ffmpeg command assembly for proxy clips |
| `test_hq_export_fast_cmd` | ffmpeg stream-copy command for original |
| `test_hq_export_precise_cmd` | ffmpeg re-encode command with double-ss trick |
| `test_export_quota_enforcement` | 31st fast export in 24h returns 429 |
| `test_export_dedup` | Same clips+mode returns existing job, not new one |
| `test_export_mode_validation` | Invalid mode returns 422 |
| `test_proxy_clip_max_duration` | >300s clip returns 400 |
| `test_edl_with_media_url` | EDL generator uses media_url when media_path is empty |
| `test_fcpxml_with_media_url` | FCPXML generator uses media_url |
| `test_video_id_prefix_routing` | `gd_*` routes to Drive export; others route to agent |

### Integration Tests (MinIO + Postgres)

| Test | What It Verifies |
|------|-----------------|
| `test_proxy_clip_e2e` | Upload proxy → request clip → cut → serve via presigned URL |
| `test_hq_export_job_lifecycle` | Create job → process → complete → poll → download → expire |
| `test_export_concurrent_same_video` | Two exports from same video share the downloaded original |
| `test_org_isolation_exports` | Org A's export job not visible to Org B |

---

## Migration Path from Agent Export

| Phase | Agent-sourced videos | Drive-sourced videos |
|-------|---------------------|---------------------|
| **Before integration** | Agent clip/EDL via localhost:8787 | N/A |
| **Phase 1 (proxy gen)** | Unchanged | No export yet (proxy only for playback) |
| **Phase 2 (export)** | Unchanged | Proxy clip via `/api/drive/clips/`, HQ via `/api/drive/exports` |
| **Future** | Optionally migrate to SaaS-side export if agent-less deployment desired | Full parity |

**The agent export path is never removed.** Drive export is additive.
