# Google Drive Proxy-First Architecture

**Date**: 2026-02-19
**Status**: Finalized (codebase-validated)
**Supersedes**: GOOGLE_DRIVE_CONNECTOR_DESIGN.md (Hybrid Lazy Mirror)
**See also**: [PR_PLAN.md](./PR_PLAN.md) · [SHORTS_EXPORT_SPEC.md](./SHORTS_EXPORT_SPEC.md) · [RUNBOOK.md](./RUNBOOK.md)

## Architecture Decision

**Proxy-First**: We download original videos from Google Drive, transcode them into a lightweight proxy (H.264 720p mezzanine), and store **only the proxy** in S3/MinIO. The original stays on Drive. For high-quality export, we fetch the original from Drive at export time.

This fundamentally differs from the previous "Hybrid Lazy Mirror" approach which mirrored original video bytes to S3. Proxy-first reduces storage costs by ~80-90% and eliminates the need to store TB-scale original files.

---

## System Context: Current Architecture

### What Exists Today

```
Desktop Agent (Go)                        SaaS (FastAPI + Next.js)
┌──────────────────────┐                  ┌─────────────────────────────┐
│ ffmpeg scenecut      │                  │ POST /api/ingest/scenes     │
│ faster-whisper STT   │  scene metadata  │   ↓                        │
│ PaddleOCR            │ ────────────────►│ SceneIngestService          │
│ insightface          │  (no video bytes)│   ├─ normalize transcripts  │
│                      │                  │   ├─ batch embed (E5 1024d) │
│ Serves video locally │                  │   └─ bulk_index → OpenSearch│
│ localhost:8787       │                  │                             │
└──────────────────────┘                  │ Thumbnails: local FS only   │
                                          │ MinIO: configured, UNUSED   │
                                          │ Task queue: NONE            │
                                          │ Video bytes: NOT stored     │
                                          └─────────────────────────────┘
```

### Key Constraints Discovered

| Aspect | Current State | Implication for Drive |
|--------|--------------|----------------------|
| Video bytes | Never touch SaaS | Drive worker must download + process server-side |
| Thumbnails | Local FS: `/data/thumbnails/{org_id}/{video_id}/{scene_id}.jpg` | Need S3 path for Drive thumbnails |
| Playback | Agent serves via `localhost:8787` | Need presigned URL endpoint for proxy |
| MinIO | In docker-compose, credentials in config, **zero client code** | Ready to use, need to write MinIO/S3 client |
| Task queue | None (all sync FastAPI) | Need background worker for proxy generation |
| `source_type` | `Literal["gdrive", "removable_disk", "local"]` — "gdrive" is DEFAULT | Already wired in search, filters, aggregations |
| Video metadata | No `videos` table — OpenSearch aggregations only | Drive file tracking needs Postgres tables |
| Pipelines | All expect local file paths | Worker downloads to temp disk, runs pipelines |
| `ExportClip` | Has both `media_path` and `media_url` fields | Prepared for remote URLs |
| Multi-tenancy | org_id from Host header, every OS query scoped | New tables must FK to orgs.id |

---

## High-Level Architecture

```
                              Google Drive (Shared Drives)
                                        │
                                        │ Drive API (DWD auth)
                                        ▼
┌─────────────────────────────────────────────────────────────────┐
│                     Drive Worker (new Docker service)           │
│                                                                 │
│  ┌──────────┐  ┌──────────────┐  ┌──────────────┐  ┌────────┐ │
│  │  Sync    │  │  Download    │  │  Transcode   │  │  Run   │ │
│  │  Engine  │  │  (chunked,   │  │  to Proxy    │  │ Pipeli-│ │
│  │          │  │  resumable)  │  │  (720p H.264)│  │  nes   │ │
│  │ Changes  │  │              │  │              │  │        │ │
│  │ API poll │  │  temp disk   │  │  ffmpeg      │  │ scenes │ │
│  │          │  │              │  │              │  │ STT    │ │
│  └────┬─────┘  └──────┬───────┘  └──────┬───────┘  │ OCR   │ │
│       │               │                 │           │ faces  │ │
│       │               │                 │           └───┬────┘ │
│       │               │                 │               │      │
│       ▼               ▼                 ▼               ▼      │
│  ┌─────────┐    ┌──────────┐    ┌──────────────┐  ┌────────┐  │
│  │Postgres │    │ temp     │    │  S3/MinIO    │  │ SaaS   │  │
│  │drive_*  │    │ cleanup  │    │  proxy.mp4   │  │ ingest │  │
│  │tables   │    │          │    │  thumbs/*.jpg│  │ API    │  │
│  └─────────┘    └──────────┘    └──────────────┘  └────────┘  │
└─────────────────────────────────────────────────────────────────┘
                                        │
                   ┌────────────────────┼──────────────────────┐
                   ▼                    ▼                      ▼
            ┌──────────┐        ┌──────────────┐       ┌──────────┐
            │ Postgres │        │  S3/MinIO    │       │OpenSearch│
            │          │        │              │       │          │
            │drive_    │        │{org}/drive/  │       │heimdex_  │
            │connections│       │{drive}/{file}│       │scenes_v1 │
            │drive_    │        │  /proxy.mp4  │       │          │
            │files     │        │  /thumbs/    │       │source_   │
            │drive_    │        │  /*.jpg      │       │type=     │
            │secrets   │        │              │       │"gdrive"  │
            └──────────┘        └──────────────┘       └──────────┘
                                        │
                                        ▼
                                 ┌──────────────┐
                                 │  FastAPI      │
                                 │  (existing)   │
                                 │               │
                                 │ GET /api/drive│
                                 │  /playback/   │
                                 │  {video_id}   │
                                 │  → presigned  │
                                 │    S3 URL     │
                                 │               │
                                 │ GET /api/     │
                                 │ thumbnails/   │
                                 │  → S3 fallback│
                                 └──────────────┘
```

---

## Data Model Design

### New Postgres Tables

#### `drive_connections`

Tracks which Shared Drives are connected per org.

```sql
CREATE TABLE drive_connections (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    library_id      UUID NOT NULL REFERENCES libraries(id) ON DELETE CASCADE,
    drive_id        TEXT NOT NULL,           -- Google Shared Drive ID (e.g., "0AFxxx")
    drive_name      TEXT NOT NULL,           -- Human-readable drive name
    status          TEXT NOT NULL DEFAULT 'active',  -- active | paused | disconnected | error
    change_token    TEXT,                    -- Drive Changes API page token (per-drive delta sync)
    last_sync_at    TIMESTAMPTZ,
    last_full_sync_at TIMESTAMPTZ,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_drive_connections_org_drive UNIQUE (org_id, drive_id)
);

CREATE INDEX ix_drive_connections_org_id ON drive_connections(org_id);
CREATE INDEX ix_drive_connections_status ON drive_connections(status);
```

#### `drive_files`

Tracks every video file discovered in connected Shared Drives.

```sql
CREATE TABLE drive_files (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id              UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    connection_id       UUID NOT NULL REFERENCES drive_connections(id) ON DELETE CASCADE,
    google_file_id      TEXT NOT NULL,           -- Google Drive file ID
    file_name           TEXT NOT NULL,           -- Original filename
    mime_type           TEXT NOT NULL,           -- e.g., "video/mp4"
    file_size_bytes     BIGINT,
    md5_checksum        TEXT,                    -- For change detection
    google_modified_time TIMESTAMPTZ,
    google_created_time TIMESTAMPTZ,
    drive_path          TEXT,                    -- Path within Shared Drive

    -- Heimdex integration
    video_id            TEXT NOT NULL,           -- "gd_{sha256(org_id:google_file_id)[:16]}"
    processing_status   TEXT NOT NULL DEFAULT 'pending',
    -- States: pending → downloading → transcoding → processing → indexing → indexed | failed | skipped
    proxy_s3_key        TEXT,                    -- S3 key for proxy: "{org_id}/drive/{drive_id}/{file_id}/proxy.mp4"
    proxy_duration_ms   INTEGER,
    proxy_size_bytes    BIGINT,
    thumbnail_s3_prefix TEXT,                    -- "{org_id}/drive/{drive_id}/{file_id}/thumbs/"
    scene_count         INTEGER DEFAULT 0,

    -- Retry / failure tracking
    retry_count         INTEGER NOT NULL DEFAULT 0,
    max_retries         INTEGER NOT NULL DEFAULT 3,
    last_error          TEXT,
    last_attempt_at     TIMESTAMPTZ,

    -- Soft delete (Drive file removed/trashed)
    is_deleted          BOOLEAN NOT NULL DEFAULT false,
    deleted_at          TIMESTAMPTZ,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_drive_files_org_file UNIQUE (org_id, google_file_id)
);

CREATE INDEX ix_drive_files_org_id ON drive_files(org_id);
CREATE INDEX ix_drive_files_connection_id ON drive_files(connection_id);
CREATE INDEX ix_drive_files_processing_status ON drive_files(processing_status);
CREATE INDEX ix_drive_files_video_id ON drive_files(video_id);
```

#### `drive_secrets`

Encrypted storage for Google service account keys.

```sql
CREATE TABLE drive_secrets (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    secret_type     TEXT NOT NULL DEFAULT 'service_account_key',
    encrypted_value BYTEA NOT NULL,          -- AES-256-GCM encrypted SA key JSON
    nonce           BYTEA NOT NULL,          -- 12-byte GCM nonce
    impersonate_email TEXT NOT NULL,         -- DWD impersonation target
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    CONSTRAINT uq_drive_secrets_org_type UNIQUE (org_id, secret_type)
);

CREATE INDEX ix_drive_secrets_org_id ON drive_secrets(org_id);
```

### Processing Status State Machine

```
                    ┌──────────┐
                    │  pending  │◄──── new file discovered or content changed
                    └────┬─────┘
                         │ worker picks up
                         ▼
                  ┌──────────────┐
                  │ downloading  │───── chunked from Drive API
                  └──────┬───────┘
                         │ download complete + MD5 verified
                         ▼
                  ┌──────────────┐
                  │ transcoding  │───── ffmpeg → 720p H.264 proxy
                  └──────┬───────┘
                         │ proxy uploaded to S3
                         ▼
                  ┌──────────────┐
                  │ processing   │───── scenes + STT + OCR + faces
                  └──────┬───────┘
                         │ pipeline complete
                         ▼
                  ┌──────────────┐
                  │  indexing    │───── SceneIngestService → OpenSearch
                  └──────┬───────┘
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
        ┌──────────┐ ┌────────┐ ┌─────────┐
        │ indexed  │ │ failed │ │ skipped │
        └──────────┘ └────────┘ └─────────┘
                       (retry     (non-video
                        ≤ 3x)     or too large)
```

### video_id Generation

For Drive-sourced videos, `video_id` is deterministically derived:

```python
import hashlib

def drive_video_id(org_id: str, google_file_id: str) -> str:
    """Deterministic video_id for Drive files. Collision-resistant, idempotent."""
    digest = hashlib.sha256(f"{org_id}:{google_file_id}".encode()).hexdigest()[:16]
    return f"gd_{digest}"
```

The `gd_` prefix ensures no collision with agent-generated video_ids (which are path-based hashes without prefix).

### OpenSearch Integration

Drive-sourced scenes are indexed using the **existing** `SceneIngestService` unchanged:

```python
# The worker calls the same service the agent uses
ingest_request = IngestScenesRequest(
    video_id=drive_file.video_id,          # "gd_abc123..."
    video_title=drive_file.file_name,       # "제품소개영상.mp4"
    library_id=connection.library_id,
    source_path=f"{connection.drive_name}/{drive_file.drive_path}",
    scenes=[
        IngestSceneDocument(
            scene_id=f"{drive_file.video_id}_scene_{i:03d}",
            source_type="gdrive",           # Existing enum value
            # ... scene data from pipeline output
        )
        for i, scene in enumerate(pipeline_result.scenes)
    ],
)
```

**No changes to `IngestScenesRequest`, `SceneIngestService`, or OpenSearch mapping required.**

### Backward Compatibility

| Component | Change Required | Risk |
|-----------|----------------|------|
| `IngestScenesRequest` | None | Zero |
| `SceneIngestService` | None | Zero |
| OpenSearch mapping | None (`source_type="gdrive"` already valid) | Zero |
| `source_type` Literal | None (already `["gdrive", "removable_disk", "local"]`) | Zero |
| Search filters/facets | None (already filter by `source_type`) | Zero |
| Video aggregation | None (composite agg on `video_id` is source-agnostic) | Zero |
| `SavedShort` model | None (`video_id` is just a string) | Zero |
| Thumbnail upload | None (agent path unchanged) | Zero |
| Thumbnail serving | Minor: add S3 fallback for Drive thumbnails | Low |

---

## Proxy Generation Specification

### ffmpeg Command

```bash
ffmpeg -i /tmp/original.mp4 \
  -vf "scale=-2:720" \
  -c:v libx264 \
  -preset fast \
  -crf 23 \
  -profile:v main \
  -level 4.0 \
  -g 48 \
  -keyint_min 48 \
  -sc_threshold 0 \
  -c:a aac \
  -b:a 128k \
  -ac 2 \
  -movflags +faststart \
  -y /tmp/proxy.mp4
```

### Spec Rationale

| Setting | Value | Reason |
|---------|-------|--------|
| Resolution | 720p (`-vf scale=-2:720`) | Sufficient for search preview and scrubbing. **OCR runs on original-resolution keyframes** (see below), not the proxy. |
| Codec | H.264 Main profile | Universal browser playback (Safari, Chrome, Firefox). No HEVC licensing issues. |
| Quality | CRF 23, fast preset | ~2-4 Mbps output. Good visual quality for preview. Fast encode. |
| GOP | 48 frames (2s at 24fps) | Accurate scrubbing. Every 2s is a seek point. |
| Audio | AAC 128k stereo | Sufficient for speech-heavy livecommerce content. |
| Container | MP4 with faststart | Enables progressive playback without full download. |

### OCR Quality Strategy (Oracle-Reviewed)

**Problem**: 720p proxy can degrade OCR accuracy on small Korean text overlays common in livecommerce.

**Solution**: Extract keyframes from the **ephemeral original** download at source resolution **before** transcoding to proxy. The processing order is:

```
1. Download original from Drive → /tmp/original.mp4
2. Run scene detection → scene boundaries
3. Extract keyframes at ORIGINAL resolution → /tmp/keyframes/*.jpg  ← OCR runs on these
4. Transcode to 720p proxy → /tmp/proxy.mp4
5. Run STT on original audio (better quality)
6. Run OCR on original-res keyframes
7. Upload proxy.mp4 + proxy-res thumbnails to S3
8. DELETE original from temp disk
9. Index scenes via SceneIngestService
```

This means the original file is **ephemeral** — it exists on temp disk only during processing, never permanently stored in S3. OCR gets the best possible input quality while storage costs remain at proxy level.

### Storage Estimates

| Original | Proxy | Ratio |
|----------|-------|-------|
| 1 GB (1080p, 30min) | ~100-150 MB (720p) | ~7-10x reduction |
| 3 GB (1080p, 90min) | ~300-450 MB | Same ratio |
| 500 videos × 3 GB avg | ~75 GB proxy total | ~$1.75/month S3 Standard |

---

## S3/MinIO Storage Layout

```
heimdex-media/                          (bucket)
  {org_id}/
    drive/
      {drive_id}/
        {google_file_id}/
          proxy.mp4                     # Transcoded 720p proxy
          thumbs/
            {scene_id}.jpg              # Keyframe thumbnails
          sidecar/
            scenes.json                 # Pipeline output (SceneDetectionResult)
            speech.json                 # STT output
    exports/
      {export_job_id}/
        clip.mp4                        # Temporary HQ export (auto-cleaned after 24h)
```

### Key Design Decisions

1. **Deterministic keys**: Idempotent re-processing overwrites the same S3 path
2. **org_id prefix**: Enables per-org lifecycle policies and access control
3. **drive_id grouping**: Matches Google Drive structure for easy mapping
4. **Separate exports dir**: Auto-cleaned via S3 lifecycle rule (expire after 24h)

---

## Drive Worker Service

### Docker Service Definition

```yaml
# Addition to docker-compose.yml
drive-worker:
  build:
    context: ./services/drive-worker
    dockerfile: Dockerfile
  container_name: heimdex-drive-worker
  environment:
    - DATABASE_URL=${DATABASE_URL:-postgresql+asyncpg://heimdex:heimdex_dev_password@postgres:5432/heimdex}
    - DATABASE_URL_SYNC=${DATABASE_URL_SYNC:-postgresql://heimdex:heimdex_dev_password@postgres:5432/heimdex}
    - MINIO_ENDPOINT=minio:9000
    - MINIO_ACCESS_KEY=${MINIO_ACCESS_KEY:-heimdex}
    - MINIO_SECRET_KEY=${MINIO_SECRET_KEY:-heimdex_dev_password}
    - MINIO_SECURE=${MINIO_SECURE:-false}
    - MINIO_BUCKET=${MINIO_BUCKET:-heimdex-media}
    - DRIVE_WORKER_ENABLED=${DRIVE_WORKER_ENABLED:-true}
    - DRIVE_SYNC_INTERVAL_SECONDS=${DRIVE_SYNC_INTERVAL_SECONDS:-300}
    - DRIVE_MAX_CONCURRENT_DOWNLOADS=${DRIVE_MAX_CONCURRENT_DOWNLOADS:-2}
    - DRIVE_MAX_FILE_SIZE_GB=${DRIVE_MAX_FILE_SIZE_GB:-10}
    - DRIVE_ENCRYPTION_KEY=${DRIVE_ENCRYPTION_KEY:-}
    - EMBEDDING_MODEL=intfloat/multilingual-e5-large
    - EMBEDDING_DIMENSION=1024
    - HF_HOME=/data/huggingface
  volumes:
    - ./services/drive-worker:/app
    - ../heimdex-media-contracts:/opt/heimdex-media-contracts:ro
    - ../heimdex-media-pipelines:/opt/heimdex-media-pipelines:ro
    - huggingface_cache:/data/huggingface
    - drive_worker_temp:/tmp/drive-downloads
  depends_on:
    postgres:
      condition: service_healthy
    minio:
      condition: service_healthy
  tmpfs:
    - /tmp/drive-processing:size=20G
```

### Worker Architecture

The worker runs as a standalone process with APScheduler for periodic sync:

```
┌─────────────────────────────────────────────┐
│              Drive Worker Process            │
│                                             │
│  ┌──────────────────────────────────────┐   │
│  │  APScheduler (BackgroundScheduler)   │   │
│  │                                      │   │
│  │  Job 1: poll_drive_changes()         │   │
│  │    runs every DRIVE_SYNC_INTERVAL_S  │   │
│  │    for each active connection:       │   │
│  │      - changes.list with page token  │   │
│  │      - upsert new/changed files      │   │
│  │      - mark deleted files            │   │
│  │                                      │   │
│  │  Job 2: process_pending_files()      │   │
│  │    runs every 30 seconds             │   │
│  │    picks N pending drive_files:      │   │
│  │      - download from Drive           │   │
│  │      - transcode to proxy            │   │
│  │      - run pipelines                 │   │
│  │      - upload to S3                  │   │
│  │      - call SceneIngestService       │   │
│  │                                      │   │
│  │  Job 3: weekly_full_reconciliation() │   │
│  │    runs once per week                │   │
│  │    full files.list to catch missed   │   │
│  │    changes                           │   │
│  └──────────────────────────────────────┘   │
└─────────────────────────────────────────────┘
```

### Why Not Celery/Dramatiq?

The current SaaS has zero task queue infrastructure. Adding Celery requires Redis/RabbitMQ, more config, more operational complexity. For v1:

- APScheduler runs in-process (no broker dependency)
- Postgres `drive_files` table acts as the job queue (`processing_status = 'pending'`)
- `SELECT FOR UPDATE SKIP LOCKED` prevents duplicate processing
- Upgrade path to Celery/Dramatiq is straightforward if needed

---

## Google Drive API Integration

### Authentication: Domain-Wide Delegation (DWD)

```python
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

def get_drive_service(sa_key: dict, impersonate_email: str):
    creds = Credentials.from_service_account_info(
        sa_key,
        scopes=["https://www.googleapis.com/auth/drive.readonly"],
        subject=impersonate_email,
    )
    return build("drive", "v3", credentials=creds)
```

### Delta Sync via Changes API

```python
async def poll_changes(connection: DriveConnection, drive_service):
    """Poll for changes since last sync."""
    page_token = connection.change_token

    if not page_token:
        # First sync: get initial token
        response = drive_service.changes().getStartPageToken(
            driveId=connection.drive_id,
            supportsAllDrives=True,
        ).execute()
        page_token = response["startPageToken"]

    while True:
        response = drive_service.changes().list(
            pageToken=page_token,
            driveId=connection.drive_id,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            fields="changes(file(id,name,mimeType,size,md5Checksum,modifiedTime,createdTime,parents,trashed),removed),nextPageToken,newStartPageToken",
            pageSize=1000,
        ).execute()

        for change in response.get("changes", []):
            await handle_change(connection, change)

        page_token = response.get("nextPageToken") or response.get("newStartPageToken")
        if "newStartPageToken" in response:
            break  # All changes consumed

    connection.change_token = page_token
    connection.last_sync_at = datetime.now(timezone.utc)
```

### Change Handling Matrix

| Change Type | Detection | Action |
|------------|-----------|--------|
| New video file | `file.mimeType.startswith("video/")` + not in drive_files | Create drive_file (status=pending) |
| Content update | `file.md5Checksum` differs from stored | Reset status=pending, clear proxy_s3_key |
| Rename | `file.name` differs | Update file_name, update OpenSearch video_title |
| Move | `file.parents[]` changed | Update drive_path |
| Delete/trash | `removed: true` or `file.trashed: true` | Set is_deleted=true, remove from OpenSearch |
| Non-video | `mimeType` not `video/*` | Skip |

### Download Strategy

**Critical**: `google-api-python-client`'s `MediaIoBaseDownload` does NOT support resume after connection drop — it always starts from byte 0 ([GitHub Issue #2309](https://github.com/googleapis/google-api-python-client/issues/2309)). For large video files (1-10 GB), use manual `Range` headers with `google.auth.transport.requests.AuthorizedSession`:

```python
from google.auth.transport.requests import AuthorizedSession

CHUNK_SIZE = 32 * 1024 * 1024  # 32 MB

async def download_file(authed_session: AuthorizedSession, file_id: str, dest_path: str, file_size: int, expected_md5: str):
    """Resume-safe chunked download with Range headers and integrity verification."""
    url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media&supportsAllDrives=true"
    start_byte = Path(dest_path).stat().st_size if Path(dest_path).exists() else 0

    with open(dest_path, "ab") as fh:  # append mode for resume
        while start_byte < file_size:
            end_byte = min(start_byte + CHUNK_SIZE - 1, file_size - 1)
            headers = {"Range": f"bytes={start_byte}-{end_byte}"}

            for attempt in range(5):
                try:
                    resp = authed_session.get(url, headers=headers, stream=True, timeout=(15, 600))
                    resp.raise_for_status()
                    for chunk in resp.iter_content(chunk_size=4 * 1024 * 1024):
                        fh.write(chunk)
                    fh.flush()
                    start_byte = Path(dest_path).stat().st_size  # ground truth from disk
                    break
                except (ConnectionError, TimeoutError):
                    if attempt == 4: raise
                    fh.flush()
                    start_byte = Path(dest_path).stat().st_size
                    time.sleep(min(64, 2**attempt) + random.uniform(0, 1))

    # Verify integrity
    import hashlib
    h = hashlib.md5()
    with open(dest_path, "rb") as f:
        for chunk in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(chunk)
    if h.hexdigest() != expected_md5:
        Path(dest_path).unlink()
        raise IntegrityError(f"MD5 mismatch: expected {expected_md5}, got {h.hexdigest()}")
```

### Rate Limit Handling

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=2, max=60),
    retry=retry_if_exception(lambda e: _is_rate_limit(e)),
)
def drive_api_call(fn, *args, **kwargs):
    """Wrapper with exponential backoff for 403/429 errors."""
    return fn(*args, **kwargs).execute()
```

---

## Playback & Thumbnail Serving

### Proxy Playback Endpoint

```python
# New endpoint: GET /api/drive/playback/{video_id}
@router.get("/playback/{video_id}")
async def get_playback_url(
    video_id: str,
    org_ctx: OrgContext = Depends(get_current_org),
):
    """Return presigned S3 URL for proxy video playback."""
    drive_file = await drive_file_repo.get_by_video_id(org_ctx.org_id, video_id)

    if not drive_file or not drive_file.proxy_s3_key:
        raise HTTPException(status_code=404, detail="Video not found or not yet processed")

    presigned_url = s3_client.generate_presigned_url(
        drive_file.proxy_s3_key,
        expiry_seconds=3600,
    )

    return RedirectResponse(
        url=presigned_url,
        status_code=302,
        headers={"Cache-Control": "no-store"},
    )
```

### Thumbnail Serving Strategy

**Approach: S3 fallback in existing endpoint** (least disruptive)

```python
# Modified: GET /api/thumbnails/{video_id}/{scene_id}
@public_router.get("/{video_id}/{scene_id}")
async def get_thumbnail(video_id: str, scene_id: str, org_ctx: OrgContext):
    settings = get_settings()

    # 1. Try local filesystem first (agent-uploaded thumbnails)
    local_path = Path(settings.thumbnail_storage_dir) / str(org_ctx.org_id) / video_id / f"{scene_id}.jpg"
    if local_path.exists():
        return FileResponse(path=local_path, media_type="image/jpeg",
                          headers={"Cache-Control": "public, max-age=86400"})

    # 2. Try S3 (Drive-sourced thumbnails)
    s3_key = f"{org_ctx.org_id}/drive/{video_id}/thumbs/{scene_id}.jpg"  # simplified lookup
    if await s3_client.object_exists(s3_key):
        presigned = s3_client.generate_presigned_url(s3_key, expiry_seconds=86400)
        return RedirectResponse(url=presigned, status_code=302,
                              headers={"Cache-Control": "public, max-age=86400"})

    raise HTTPException(status_code=404, detail="Thumbnail not found")
```

**Note**: For `video_id` starting with `gd_`, the S3 path lookup can be optimized since we know it's a Drive video. The fallback only adds ~1 extra check for agent thumbnails (which hit local FS first).

---

## Async HQ Export

### Architecture

For high-quality export (Premiere XML, shorts cut from original), the system fetches the original from Drive at export time:

```
User clicks "Export HQ"
        │
        ▼
POST /api/drive/exports
  → creates export_jobs row (status=pending)
  → returns job_id (202 Accepted)
        │
        ▼
Drive Worker picks up job
  → downloads original from Drive (chunked, resumable)
  → cuts clip with ffmpeg (stream copy, no transcode)
  → uploads to S3: exports/{job_id}/clip.mp4
  → updates export_jobs (status=completed, presigned_url)
        │
        ▼
GET /api/drive/exports/{job_id}
  → returns { status, download_url, expires_at }
        │
        ▼
S3 lifecycle rule: auto-delete exports/ after 24h
```

### Export Job Table

```sql
CREATE TABLE drive_export_jobs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          UUID NOT NULL REFERENCES orgs(id) ON DELETE CASCADE,
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    drive_file_id   UUID NOT NULL REFERENCES drive_files(id),
    video_id        TEXT NOT NULL,
    start_ms        INTEGER NOT NULL,
    end_ms          INTEGER NOT NULL,
    export_type     TEXT NOT NULL DEFAULT 'clip',  -- 'clip' | 'full' | 'fcpxml'
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending | downloading | processing | completed | failed | expired
    s3_key          TEXT,
    file_size_bytes BIGINT,
    error_message   TEXT,
    retry_count     INTEGER NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    expires_at      TIMESTAMPTZ,           -- created_at + 24h

    CONSTRAINT uq_export_jobs_org_user_dedup UNIQUE (org_id, user_id, drive_file_id, start_ms, end_ms)
);

CREATE INDEX ix_drive_export_jobs_status ON drive_export_jobs(status);
CREATE INDEX ix_drive_export_jobs_org_user ON drive_export_jobs(org_id, user_id);
```

### Per-Org Export Quota

Enforced in Postgres (no Redis needed for v1):

```python
DAILY_EXPORT_LIMIT = 20  # per org

async def check_export_quota(org_id: UUID) -> bool:
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    count = await export_repo.count_since(org_id, since)
    return count < DAILY_EXPORT_LIMIT
```

### Failure & Timeout Strategy

| Failure | Action |
|---------|--------|
| Drive download fails (transient) | Retry up to 3x with exponential backoff |
| Drive download fails (permanent: 404, permission) | Mark failed, notify user |
| ffmpeg clip cut fails | Mark failed, retry 1x |
| S3 upload fails | Retry up to 3x |
| Job exceeds 30 min timeout | Kill process, mark failed |
| Export not downloaded within 24h | S3 lifecycle auto-deletes, status → expired |

---

## Security & Tenancy

### Org Isolation Verification

| Layer | Mechanism | Drive Addition |
|-------|-----------|---------------|
| API routing | TenancyMiddleware → org from Host subdomain | Same — all Drive endpoints use `OrgContext` |
| Postgres | FK to `orgs.id` on every table | `drive_connections.org_id`, `drive_files.org_id`, `drive_secrets.org_id` all FK to orgs |
| OpenSearch | `{"term": {"org_id": org_id}}` in every query | Same — SceneIngestService stamps `org_id` |
| S3 keys | Prefixed with `{org_id}/` | Deterministic: `{org_id}/drive/{drive_id}/{file_id}/...` |
| Drive API | DWD scoped to customer's Workspace | Each org has its own SA key in `drive_secrets` |

### Token Safety

- Google SA keys encrypted at rest (AES-256-GCM) in `drive_secrets`
- Encryption key from env var `DRIVE_ENCRYPTION_KEY`
- Access tokens never exposed to frontend
- Presigned URLs have 1h expiry (playback) or 24h expiry (exports)
- No credentials in logs (structlog with key redaction)

### Cross-Org Leakage Prevention

- Drive worker processes files **one org at a time** (org_id in every query)
- S3 presigned URLs contain org_id in path (cannot access other org's files)
- OpenSearch composite doc_id = `{org_id}:{scene_id}` prevents cross-tenant overwrites
- Export jobs validated: `org_id` from auth must match job's `org_id`

---

## Configuration Additions

### config.py Extensions

```python
class Settings(BaseSettings):
    # ... existing settings ...

    # --- Google Drive integration ---
    drive_connector_enabled: bool = False
    drive_encryption_key: str = ""           # AES-256 key for SA key encryption
    drive_sync_interval_seconds: int = 300   # Delta sync poll interval
    drive_max_concurrent_downloads: int = 2  # Per-worker download parallelism
    drive_max_file_size_gb: int = 10         # Skip files larger than this
    drive_proxy_resolution: int = 720        # Proxy video height in pixels
    drive_proxy_crf: int = 23               # ffmpeg CRF quality
    drive_export_daily_limit: int = 20      # Per-org daily HQ export limit
    drive_export_ttl_hours: int = 24        # Export file retention
```

### Feature Flag

The entire Drive module is gated behind `DRIVE_CONNECTOR_ENABLED=true`:
- API routes return 404 when disabled
- Worker skips Drive jobs when disabled
- Migration runs regardless (schema is always present)

---

## API Endpoints (New)

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| POST | `/api/drive/secrets` | JWT | Upload encrypted SA key |
| POST | `/api/drive/connect` | JWT | Connect a Shared Drive |
| GET | `/api/drive/connections` | JWT | List org's connections |
| GET | `/api/drive/connections/{id}` | JWT | Connection detail + file stats |
| POST | `/api/drive/connections/{id}/sync` | JWT | Trigger manual sync |
| DELETE | `/api/drive/connections/{id}` | JWT | Disconnect (soft delete) |
| GET | `/api/drive/connections/{id}/files` | JWT | List tracked files with status |
| GET | `/api/drive/playback/{video_id}` | JWT | 302 → presigned S3 URL for proxy |
| POST | `/api/drive/exports` | JWT | Create HQ export job |
| GET | `/api/drive/exports/{job_id}` | JWT | Export status + download URL |
| POST | `/api/drive/test-connection` | JWT | Test DWD auth (spike only) |

---

## Dependency Graph

```
heimdex-media-contracts/    ← NO CHANGES (source_type agnostic)
        │
heimdex-media-pipelines/    ← NO CHANGES (local file path contract unchanged)
        │
        │ installed as editable in drive-worker container
        │
dev-heimdex-for-livecommerce/
├── services/api/
│   ├── app/config.py              ← ADD drive_* settings
│   ├── app/main.py                ← ADD drive router registration
│   ├── app/dependencies.py        ← ADD drive service factories
│   ├── app/db/models.py           ← ADD drive model imports
│   ├── app/db/migrations/
│   │   └── versions/
│   │       └── 012_create_drive_tables.py  ← NEW
│   ├── app/modules/drive/         ← NEW MODULE
│   │   ├── models.py              # DriveConnection, DriveFile, DriveSecret
│   │   ├── repository.py          # CRUD for drive tables
│   │   ├── schemas.py             # API request/response DTOs
│   │   ├── router.py              # All /api/drive/* endpoints
│   │   ├── google_client.py       # Drive API wrapper
│   │   ├── sync_service.py        # Delta sync orchestration
│   │   ├── secrets.py             # AES-256-GCM encrypt/decrypt
│   │   └── s3_client.py           # MinIO/S3 operations
│   └── app/modules/thumbnails/
│       └── router.py              ← MODIFY: add S3 fallback
│
├── services/drive-worker/         ← NEW SERVICE
│   ├── Dockerfile
│   ├── pyproject.toml
│   └── src/
│       ├── worker.py              # APScheduler entrypoint
│       ├── config.py              # Worker config
│       └── tasks/
│           ├── sync.py            # poll_drive_changes
│           ├── process.py         # download → transcode → pipeline → index
│           ├── export.py          # HQ export from Drive
│           └── cleanup.py         # Temp file cleanup
│
├── services/web/                  ← MODIFY: add Drive connection UI
│   └── src/
│       ├── app/settings/drive/    # Drive management page
│       └── components/
│           └── VideoPlayer.tsx    # Handle source_type="gdrive" → proxy URL
│
└── docker-compose.yml             ← ADD drive-worker service
```

---

## Migration Plan

### Alembic Migration: `012_create_drive_tables.py`

Follows existing convention (`{NNN}_{description}`). Previous migration is `011_add_people_exclude_preferences_table`.

```python
revision = "012_create_drive_tables"
down_revision = "011_add_people_exclude_preferences_table"

def upgrade():
    # Create drive_secrets first (no FK deps except orgs)
    # Create drive_connections (FK to orgs, libraries)
    # Create drive_files (FK to orgs, drive_connections)
    # Create drive_export_jobs (FK to orgs, users, drive_files)
    pass

def downgrade():
    # Drop in reverse order
    op.drop_table("drive_export_jobs")
    op.drop_table("drive_files")
    op.drop_table("drive_connections")
    op.drop_table("drive_secrets")
```

**Safety**: All tables are new. No existing table modifications. Migration is fully reversible via `downgrade()`. FK references only to existing tables (`orgs`, `libraries`, `users`).

---

## Failure Modes

| Failure | Impact | Mitigation |
|---------|--------|-----------|
| Drive API rate limit (12k req/60s) | Sync/download slows | Exponential backoff, per-org rate limiter |
| DWD propagation delay (up to 24h) | New connections fail auth | Retry with guidance; test endpoint shows clear error |
| Large file download interrupted | Wasted bandwidth | Chunked + resumable; track bytes_downloaded |
| Worker crashes mid-processing | Orphan temp files, stuck status | Heartbeat check; reset stale `downloading` status after 30min |
| S3/MinIO unavailable | Can't store proxy | Retry; circuit breaker; health check |
| OCR degradation on 720p proxy | Lower text extraction accuracy | Accept for v1; option to download original keyframes for OCR in v2 |
| Google SA key rotation | Auth fails silently | Monitoring; re-upload endpoint; clear error messaging |
| Export quota exhausted | User can't export | Clear UX messaging with reset time |

---

## Codebase Validation (2026-02-19)

All claims in this document have been verified against the actual codebase:

### source_type="gdrive" — CONFIRMED GENUINE

Exhaustive audit across all 4 repos found `source_type` in 237 locations. Classification:

| Layer | Status | Evidence |
|-------|--------|---------|
| Schema (Pydantic) | `Literal["gdrive", "removable_disk", "local"]` with default="gdrive" | `services/api/app/modules/ingest/schemas.py:83-86` |
| OpenSearch mapping | `"source_type": {"type": "keyword"}` | `services/api/app/modules/search/scene_client.py:237` |
| Ingest path | Indexed in `bulk_index_scenes()` | `services/api/app/modules/ingest/service.py:141` |
| Search filter | `{"terms": {"source_type": ...}}` in `_build_filter_clauses()` | `services/api/app/modules/search/scene_client.py:992-993` |
| Video aggregation | Composite agg includes source_type | `services/api/app/modules/search/scene_client.py:673-715` |
| Facets | Aggregation returned in search responses | `services/api/app/modules/search/scene_client.py:603` |
| Agent (Go) | `resolveSourceType()` switch handles all 3 values | `heimdex-agent/internal/catalog/runner.go:605-618` |
| Frontend badges | All 3 values rendered: gdrive→blue, removable_disk→orange, local→green | `services/web/src/features/videos/components/VideoCard.tsx:68-76` |
| Frontend labels | gdrive→"Google Drive", removable_disk→"외장 디스크", local→"로컬 파일" | `services/web/src/features/videos/components/VideoDetailPage.tsx:157-161` |
| Tests | 59+ test cases reference source_type | Across 12 test files |

**No conditional logic blocks gdrive.** The only source_type conditional is for `removable_disk` (sets `required_drive_nickname`), which is semantically correct — gdrive and local don't need it.

### Thumbnails — LOCAL FS ONLY

- Upload: `POST /api/ingest/thumbnails/{video_id}` → writes to `{thumbnail_storage_dir}/{org_id}/{video_id}/{scene_id}.jpg` (`services/api/app/modules/thumbnails/router.py:39-68`)
- Serve: `GET /api/thumbnails/{video_id}/{scene_id}` → `FileResponse` from local path (`router.py:88-103`)
- Frontend fallback: cloud (API) → agent (localhost:8787) → placeholder (`services/web/src/components/SceneThumbnail.tsx:40-61`)
- **No S3 client code exists anywhere.** No `boto3` or `minio-py` in `pyproject.toml`.

### MinIO — CONFIGURED BUT ZERO CLIENT CODE

- Docker service: running on port 9000/9001 (`docker-compose.yml:48-64`)
- Config: `minio_endpoint`, `minio_access_key`, `minio_secret_key`, `minio_secure` in `config.py:31-34`
- API env vars: passed to container (`docker-compose.yml:75-78`)
- **Usage: NONE.** No imports, no client instantiation, no upload/download code.

### Playback — AGENT-LOCAL ONLY

- `getAgentPlaybackUrl()`: `http://127.0.0.1:8787/playback/file?file_id=...` (`services/web/src/lib/agent.ts:69-75`)
- No SaaS-side video serving endpoint exists.

### Export — AGENT-ONLY, ExportClip.media_url UNUSED

- `ExportClip` has `media_path=""` and `media_url=""` (`heimdex-media-contracts/.../exports/schemas.py:14-35`)
- Only `media_path` is populated (by agent's `resolveClip()` in Go)
- `media_url` was designed for remote URLs — ready for Drive integration
- EDL/FCPXML generators reference `media_path` — need 1-line fallback to `media_url`

### Two-Tier Shorts + Export

See [SHORTS_EXPORT_SPEC.md](./SHORTS_EXPORT_SPEC.md) for the complete design:
- **Tier A (Proxy Preview)**: stream-copy from S3 proxy, ±0-2s accuracy, instant
- **Tier B (HQ Export)**: fetch original from Drive, `fast` (stream-copy) or `precise` (re-encode, ±1 frame)

---

## Pattern A: Drive-Worker ↔ API Decoupling

### Problem

The drive-worker originally imported `SceneIngestService` directly, which required
`OPENSEARCH_URL` and `EMBEDDING_USE_MOCK` in the worker environment and a direct
`depends_on: opensearch` in docker-compose. This made the worker coupled to
OpenSearch configuration and the embedding model — concerns that belong solely to
the API service.

### Solution

The drive-worker now calls `POST /internal/ingest/scenes` on the API service over
the Docker network instead of importing `SceneIngestService` directly.

```
drive-worker                         API service
┌──────────────┐    HTTP POST        ┌──────────────────────┐
│ process.py   │ ──────────────────► │ /internal/ingest/    │
│              │ Bearer internal key  │   scenes             │
│ builds scene │ X-Heimdex-Org-Id   │                      │
│ payload      │                     │ SceneIngestService   │
│              │ ◄────────────────── │   normalize          │
│ checks       │  { indexed_count }  │   embed              │
│ response     │                     │   bulk_index → OS    │
└──────────────┘                     └──────────────────────┘
```

### Auth

- Pre-shared key: `DRIVE_INTERNAL_API_KEY` (same value in both API and drive-worker env)
- org_id passed via `X-Heimdex-Org-Id` header (drive-worker is internal, not a tenant)
- Endpoint feature-gated behind `DRIVE_CONNECTOR_ENABLED=true`

### What changed

| Before | After |
|--------|-------|
| drive-worker imports `SceneIngestService`, `SceneSearchClient` | drive-worker calls `POST /internal/ingest/scenes` via `requests` |
| drive-worker needs `OPENSEARCH_URL`, `EMBEDDING_USE_MOCK` | drive-worker only needs `DRIVE_API_BASE_URL`, `DRIVE_INTERNAL_API_KEY` |
| drive-worker `depends_on: opensearch` | drive-worker `depends_on: api` |
| OpenSearch/embedding config in two places | OpenSearch/embedding config only in API service |

### Implementation Gate: Phase 0 → Phase 1

See [PR_PLAN.md](./PR_PLAN.md) for the full gate criteria.
