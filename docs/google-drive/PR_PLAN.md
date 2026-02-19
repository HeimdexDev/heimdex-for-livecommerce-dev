# PR Plan: Proxy-First Google Drive Integration

**Date**: 2026-02-19
**Status**: Finalized (codebase-validated)
**Reference**: [ARCHITECTURE.md](./ARCHITECTURE.md) · [SHORTS_EXPORT_SPEC.md](./SHORTS_EXPORT_SPEC.md) · [RUNBOOK.md](./RUNBOOK.md)

---

## Overview

4 phases, 10 PRs, estimated **9-12 weeks** (single engineer). Each PR is independently merge-safe and rollback-safe. Feature-flagged behind `DRIVE_CONNECTOR_ENABLED=true` (default `false`).

**Ground rules**:
- No existing agent/local ingest paths modified
- Alembic migration runs in Phase 1; tables are inert when feature is disabled
- `heimdex-media-pipelines` and `heimdex-media-contracts` receive **zero code changes** (mounted read-only)
- `heimdex-agent` receives **zero changes**

---

## Implementation Gate: Phase 0 → Phase 1

Phase 0 is a throwaway spike. All of the following must be true before starting Phase 1:

| # | Exit Criterion | Verification |
|---|---------------|-------------|
| 1 | DWD auth succeeds against a real Shared Drive | Spike script authenticates via SA key + impersonation, no HTTP errors |
| 2 | `files.list` returns video files with metadata | Spike returns `id, name, mimeType, size, md5Checksum, modifiedTime` for at least 5 videos |
| 3 | `changes.list` delta detects new/modified/deleted files | Add a file → spike detects it. Delete a file → spike detects removal. |
| 4 | `getStartPageToken` → `changes.list` → persist token → resume works | Token saved to disk, spike restarts, resumes from saved token without replaying old changes |
| 5 | Chunked download completes for a 1 GB+ video | Downloaded file on disk matches Drive's `md5Checksum` |
| 6 | Download resumes after interruption | Kill download at ~500 MB, restart, picks up from byte 500M (Range header), completes, MD5 matches |
| 7 | Rate limit backoff works | Force rate limit (rapid requests) → script backs off and retries → succeeds |
| 8 | DWD propagation timing documented | Actual observed delay noted (minutes? hours?) |
| 9 | Findings documented | Written to `docs/google-drive/SPIKE_FINDINGS.md` |

**If any criterion fails**: investigate root cause, do not proceed to Phase 1. Common blockers: DWD scope wrong, SA key doesn't have domain-wide delegation, Shared Drive permissions.

---

## Phase 0 — Spike: DWD Auth + Drive API Connectivity

**Goal**: Prove Drive API integration works. Throwaway scripts, not merged to production code.

**Duration**: 3-5 days

### Deliverables

| # | File | Description |
|---|------|-------------|
| 1 | `scripts/drive-spike/auth_test.py` | DWD auth + `files.list` on a Shared Drive |
| 2 | `scripts/drive-spike/changes_test.py` | `changes.list` delta sync with page token round-trip |
| 3 | `scripts/drive-spike/download_test.py` | Chunked resumable download (Range headers, NOT MediaIoBaseDownload) with MD5 verify |
| 4 | `scripts/drive-spike/requirements.txt` | google-api-python-client, google-auth, requests |
| 5 | `docs/google-drive/SPIKE_FINDINGS.md` | Rate limits observed, DWD timing, download throughput |

### Prerequisites

- Google Cloud project with Drive API enabled
- Service account with DWD in a test Workspace
- A Shared Drive with 5+ video files (100 MB, 1 GB, 5 GB)

### Risk: Low. Rollback: Delete `scripts/drive-spike/`.

---

## Phase 1 — Core: Proxy Generation + Playback

### PR 1.1 — Data Model + Drive Module Skeleton

**Files to add:**

| Path | Description |
|------|-------------|
| `services/api/app/db/migrations/versions/012_create_drive_tables.py` | Alembic migration: `drive_secrets`, `drive_connections`, `drive_files`, `drive_export_jobs` |
| `services/api/app/modules/drive/__init__.py` | Module init |
| `services/api/app/modules/drive/models.py` | SQLAlchemy: `DriveConnection`, `DriveFile`, `DriveSecret`, `DriveExportJob` |
| `services/api/app/modules/drive/schemas.py` | Pydantic: request/response DTOs for all Drive endpoints |
| `services/api/app/modules/drive/router.py` | Empty router with feature flag gate returning 404 when disabled |
| `services/api/tests/test_drive_models.py` | Model CRUD tests |
| `services/api/tests/test_drive_feature_flag.py` | Feature flag gate tests |

**Files to modify:**

| Path | Change |
|------|--------|
| `services/api/app/db/models.py` | Add `from app.modules.drive.models import *` (line ~12, after shorts import) |
| `services/api/app/config.py` | Add `drive_connector_enabled: bool = False` + all `drive_*` settings (after line 123) |
| `services/api/app/main.py` | Conditional router registration: `if settings.drive_connector_enabled: app.include_router(drive_router)` |
| `services/api/app/dependencies.py` | Add drive service factory stubs (after existing factories) |

**Tests:**

| Test | What It Verifies |
|------|-----------------|
| `test_migration_up_down` | `alembic upgrade head` → `alembic downgrade 011` round-trip |
| `test_model_crud` | Create/read/update DriveConnection, DriveFile, DriveSecret |
| `test_feature_flag_disabled` | All `/api/drive/*` return 404 when `drive_connector_enabled=false` |
| `test_config_defaults` | All drive settings have safe defaults (disabled, no secrets required) |

**Feature flag when disabled**: All routes return 404. Models exist but are never queried. Migration runs (empty tables).

**Security checklist:**
- [ ] `drive_encryption_key` default is empty string (not a weak key)
- [ ] No secrets in migration file
- [ ] DriveSecret model field is `BYTEA` (not `TEXT`)

**Operational checklist:**
- [ ] Migration is reversible via `alembic downgrade 011`
- [ ] Config defaults don't require env vars to start API

**Risk**: Low. **Rollback**: `alembic downgrade 011`, remove module directory, revert 3 one-line changes.

---

### PR 1.2 — S3/MinIO Client + Secrets Manager

**Files to add:**

| Path | Description |
|------|-------------|
| `services/api/app/modules/drive/s3_client.py` | `S3Client`: upload, download, presigned_url, exists, delete. Uses `boto3` with MinIO endpoint from `config.py:31-34`. |
| `services/api/app/modules/drive/secrets.py` | `encrypt_sa_key()`, `decrypt_sa_key()` — AES-256-GCM via `cryptography` package |
| `services/api/app/modules/drive/repository.py` | CRUD for all 4 drive tables. `SELECT FOR UPDATE SKIP LOCKED` for job queue. |
| `services/api/app/modules/drive/google_client.py` | `DriveClient`: DWD auth, `files.list`, `changes.list`, resumable download (manual Range headers, NOT MediaIoBaseDownload) |
| `services/api/tests/test_s3_client.py` | S3 integration tests (against MinIO in docker-compose) |
| `services/api/tests/test_drive_secrets.py` | Encrypt/decrypt round-trip, wrong key fails, tampered ciphertext fails |
| `services/api/tests/test_drive_repository.py` | CRUD + `SKIP LOCKED` behavior |
| `services/api/tests/test_google_client.py` | Mocked Drive API responses (no real Google calls in CI) |

**Files to modify:**

| Path | Change |
|------|--------|
| `services/api/pyproject.toml` | Add: `google-api-python-client>=2.100`, `google-auth>=2.25`, `boto3>=1.34`, `cryptography>=42.0` |
| `services/api/app/modules/drive/router.py` | Add `POST /api/drive/secrets`, `POST /api/drive/test-connection` |
| `services/api/app/config.py` | Add `minio_bucket: str = "heimdex-media"` (after line 34) |

**Tests:**

| Test | What It Verifies |
|------|-----------------|
| `test_s3_upload_download_roundtrip` | Upload → exists → download → delete (MinIO) |
| `test_s3_presigned_url` | Generated URL is valid and expires correctly |
| `test_encrypt_decrypt_roundtrip` | `decrypt(encrypt(key)) == key` |
| `test_encrypt_wrong_key_fails` | Different encryption key → `InvalidTag` exception |
| `test_encrypt_tampered_ciphertext` | Modified ciphertext → `InvalidTag` exception |
| `test_repository_skip_locked` | Two concurrent `SELECT FOR UPDATE SKIP LOCKED` don't pick same row |
| `test_google_client_files_list` | Mock returns paginated video files |
| `test_google_client_changes_list` | Mock returns changes with correct page token handling |
| `test_google_client_invalid_token` | Mock 400 → client re-bootstraps token |
| `test_post_secrets_stores_encrypted` | `POST /api/drive/secrets` → DB contains encrypted bytes, not plaintext |
| `test_test_connection_calls_drive` | `POST /api/drive/test-connection` → mocked Drive API → success/error |

**Feature flag when disabled**: `POST /api/drive/secrets` and `POST /api/drive/test-connection` return 404.

**Security checklist:**
- [ ] SA key JSON never logged (even at DEBUG level)
- [ ] `DRIVE_ENCRYPTION_KEY` never in API responses
- [ ] Encrypted value uses unique nonce per encryption
- [ ] S3 client uses internal Docker network (minio:9000), not public endpoint
- [ ] `google-auth` scopes limited to `drive.readonly`

**Operational checklist:**
- [ ] S3 client handles MinIO being down (clear error, not crash)
- [ ] Google client handles rate limits (exponential backoff with jitter)
- [ ] `test-connection` has 10s timeout (don't hang on DWD issues)

**Risk**: Medium. **Rollback**: Remove new files, revert pyproject.toml.

---

### PR 1.3 — Drive Connection Management API

**Files to add:**

| Path | Description |
|------|-------------|
| `services/api/app/modules/drive/sync_service.py` | `SyncService`: initial file discovery (`files.list`), delta sync (`changes.list`), change handling, `video_id` generation (`gd_{sha256(org_id:google_file_id)[:16]}`) |
| `services/api/tests/test_sync_service.py` | Sync logic tests with mocked Drive API |
| `services/api/tests/test_drive_router.py` | Connection CRUD endpoint tests |

**Files to modify:**

| Path | Change |
|------|--------|
| `services/api/app/modules/drive/router.py` | Add: `POST /connect`, `GET /connections`, `GET /connections/{id}`, `DELETE /connections/{id}`, `GET /connections/{id}/files`, `POST /connections/{id}/sync` |
| `services/api/app/modules/drive/schemas.py` | Add connection/file list DTOs |

**Tests:**

| Test | What It Verifies |
|------|-----------------|
| `test_connect_shared_drive` | `POST /connect` → creates connection + populates drive_files |
| `test_files_list_pagination` | Mock 2500 files across 3 pages → all in DB |
| `test_delta_sync_new_file` | New file detected → drive_file created (status=pending) |
| `test_delta_sync_content_update` | MD5 change → status reset to pending, old proxy_s3_key cleared |
| `test_delta_sync_rename` | File renamed → file_name updated |
| `test_delta_sync_delete` | File trashed → is_deleted=true |
| `test_video_id_deterministic` | Same org_id+google_file_id → same video_id every time |
| `test_video_id_no_collision` | Different org or file → different video_id |
| `test_disconnect_soft_delete` | `DELETE /connections/{id}` → connection status=disconnected, files marked deleted |
| `test_org_isolation` | Org A's connection not visible to Org B |
| `test_manual_sync_trigger` | `POST /connections/{id}/sync` → calls delta sync immediately |

**Feature flag when disabled**: All connection endpoints return 404.

**Security checklist:**
- [ ] `video_id` hash includes `org_id` (prevents cross-org collision)
- [ ] Connection endpoints require JWT auth
- [ ] Org context from TenancyMiddleware (never from request body)

**Operational checklist:**
- [ ] Initial file discovery handles 10,000+ files without timeout
- [ ] Change token persisted atomically (DB transaction)
- [ ] Invalid page token → automatic re-bootstrap with full rescan

**Risk**: Medium. **Rollback**: Revert router/sync_service. Connections become inert.

---

### PR 1.4 — Drive Worker Service

**Files to add:**

| Path | Description |
|------|-------------|
| `services/drive-worker/Dockerfile` | Python 3.11 + ffmpeg + pipeline deps |
| `services/drive-worker/pyproject.toml` | apscheduler, sqlalchemy, boto3, google SDK |
| `services/drive-worker/src/__init__.py` | Package init |
| `services/drive-worker/src/worker.py` | APScheduler entrypoint: `poll_drive_changes()` (every SYNC_INTERVAL), `process_pending_files()` (every 30s), `weekly_reconciliation()` |
| `services/drive-worker/src/config.py` | Worker config from env vars |
| `services/drive-worker/src/tasks/__init__.py` | Package init |
| `services/drive-worker/src/tasks/sync.py` | Calls `SyncService.delta_sync()` per active connection |
| `services/drive-worker/src/tasks/process.py` | Pipeline: download → scene detect → original-res keyframes → transcode 720p → STT → OCR → upload S3 → SceneIngestService → delete original |
| `services/drive-worker/src/tasks/cleanup.py` | Temp file cleanup, stale job reset |
| `services/drive-worker/tests/test_process.py` | Processing task unit tests |
| `services/drive-worker/tests/test_sync.py` | Sync task unit tests |

**Files to modify:**

| Path | Change |
|------|--------|
| `docker-compose.yml` | Add `drive-worker` service (after `face-worker`, ~line 183). Depends on `postgres` (healthy) + `minio` (healthy). Mounts `heimdex-media-contracts` and `heimdex-media-pipelines` read-only. 20GB tmpfs at `/tmp/drive-processing`. |

**Processing pipeline (within `process.py`):**

```
1. SELECT drive_file WHERE status='pending' FOR UPDATE SKIP LOCKED LIMIT 1
2. Set status='downloading'
3. Download original → /tmp/drive-processing/{file_id}/original.mp4 (Range headers, resume-safe)
4. Verify MD5
5. Set status='transcoding'
6. detect_scenes(original) → scene boundaries
7. extract_all_keyframes(original, scenes) → /tmp/.../keyframes/*.jpg (ORIGINAL resolution for OCR)
8. ffmpeg transcode: original → proxy.mp4 (720p H.264, CRF 23, GOP 48, faststart)
9. Set status='processing'
10. speech transcribe(original) → STT JSON (original audio = better quality)
11. enrich_scenes_with_ocr(scenes, keyframes) → OCR on original-res keyframes
12. Upload proxy.mp4 to S3: {org_id}/drive/{drive_id}/{file_id}/proxy.mp4
13. Upload proxy-res thumbnails to S3: .../thumbs/{scene_id}.jpg
14. Upload sidecar: .../sidecar/scenes.json, speech.json
15. Set status='indexing'
16. Call SceneIngestService(source_type='gdrive') — identical to agent path
17. Set status='indexed', update scene_count, proxy_s3_key, proxy_size_bytes
18. DELETE /tmp/drive-processing/{file_id}/ (original + all temp files)
```

**Tests:**

| Test | What It Verifies |
|------|-----------------|
| `test_process_full_lifecycle` | pending → downloading → transcoding → processing → indexing → indexed |
| `test_process_idempotent` | Re-running on indexed file is no-op |
| `test_process_download_failure` | Drive 404 → status=failed, retry_count++ |
| `test_process_transcode_failure` | ffmpeg exit code != 0 → status=failed |
| `test_process_md5_mismatch` | Wrong MD5 → status=failed, temp file deleted |
| `test_stale_reset` | File in `downloading` >30min → reset to pending on worker startup |
| `test_concurrent_no_duplicate` | Two worker instances don't pick same file (SKIP LOCKED) |
| `test_temp_cleanup_on_success` | /tmp dir cleaned after successful processing |
| `test_temp_cleanup_on_failure` | /tmp dir cleaned after failed processing |
| `test_max_file_size_skip` | File >DRIVE_MAX_FILE_SIZE_GB → status=skipped |

**Feature flag when disabled**: Worker starts but skips all Drive jobs.

**Security checklist:**
- [ ] Worker decrypts SA keys one org at a time
- [ ] `DRIVE_ENCRYPTION_KEY` required (worker refuses to start without it)
- [ ] No SA key material in logs
- [ ] S3 upload uses org_id prefix (tenant isolation)

**Operational checklist:**
- [ ] Worker logs: file_id, processing_status transitions, duration per step
- [ ] Stale job detection on worker startup
- [ ] tmpfs size limit prevents disk exhaustion
- [ ] `DRIVE_MAX_FILE_SIZE_GB` enforced before download
- [ ] Exponential backoff on Drive API errors
- [ ] Docker restart policy: `unless-stopped`

**Risk**: **HIGH** — most complex PR. **Rollback**: Remove `drive-worker` from docker-compose. Pending files stay in DB but are never processed.

---

### PR 1.5 — Playback + Thumbnail Serving

**Files to add:**

| Path | Description |
|------|-------------|
| `services/api/tests/test_drive_playback.py` | Playback endpoint tests |
| `services/api/tests/test_thumbnail_s3_fallback.py` | S3 fallback tests |

**Files to modify:**

| Path | Change | Exact Location |
|------|--------|---------------|
| `services/api/app/modules/drive/router.py` | Add `GET /api/drive/playback/{video_id}` → 302 presigned S3 URL | New route |
| `services/api/app/modules/thumbnails/router.py` | Add S3 fallback after local FS check at line 96 | Between `if not thumbnail_path.exists():` and `raise HTTPException` |

**Thumbnail router change (minimal):**

```python
# Current (router.py:88-103):
@public_router.get("/{video_id}/{scene_id}")
async def get_thumbnail(video_id, scene_id, org_ctx):
    thumbnail_path = Path(settings.thumbnail_storage_dir) / str(org_ctx.org_id) / video_id / f"{scene_id}.jpg"
    if not thumbnail_path.exists():
        raise HTTPException(status_code=404)
    return FileResponse(path=thumbnail_path, ...)

# Modified:
@public_router.get("/{video_id}/{scene_id}")
async def get_thumbnail(video_id, scene_id, org_ctx):
    # 1. Try local filesystem first (agent-uploaded, unchanged)
    thumbnail_path = Path(settings.thumbnail_storage_dir) / str(org_ctx.org_id) / video_id / f"{scene_id}.jpg"
    if thumbnail_path.exists():
        return FileResponse(path=thumbnail_path, ...)

    # 2. S3 fallback for Drive-sourced thumbnails (only check for gd_ prefix)
    if video_id.startswith("gd_") and settings.drive_connector_enabled:
        s3 = get_s3_client()
        s3_key = f"{org_ctx.org_id}/drive/{video_id}/thumbs/{scene_id}.jpg"  # simplified lookup
        if await s3.exists(s3_key):
            url = s3.presigned_url(s3_key, expiry=86400)
            return RedirectResponse(url=url, status_code=302, headers={"Cache-Control": "public, max-age=86400"})

    raise HTTPException(status_code=404)
```

**Tests:**

| Test | What It Verifies |
|------|-----------------|
| `test_playback_valid_video` | Indexed Drive video → 302 with presigned URL |
| `test_playback_missing_video` | Unknown video_id → 404 |
| `test_playback_unprocessed_video` | `processing_status != indexed` → 404 |
| `test_playback_wrong_org` | Org A's video queried by Org B → 404 (not 403) |
| `test_playback_cache_control` | Response has `Cache-Control: no-store` |
| `test_thumbnail_local_unchanged` | Agent-uploaded thumb → FileResponse (regression) |
| `test_thumbnail_s3_fallback` | gd_ video, no local file, S3 exists → 302 presigned URL |
| `test_thumbnail_s3_not_found` | gd_ video, no local, no S3 → 404 |
| `test_thumbnail_non_drive_no_s3_check` | Non-gd_ video, no local → 404 (no S3 check, no latency) |

**Feature flag when disabled**: Playback returns 404. Thumbnail S3 fallback skipped (existing local FS path unchanged).

**Security checklist:**
- [ ] Presigned URL contains org_id in S3 key path (can't access other org's files)
- [ ] Playback URL has 1h expiry
- [ ] No video bytes flow through FastAPI (redirect only)

**Operational checklist:**
- [ ] Thumbnail fallback only checks S3 for `gd_` prefix (no latency for agent thumbnails)
- [ ] Presigned URL generation is server-side (no MinIO credentials exposed to frontend)

**Risk**: Low (playback), Medium (thumbnail modification — touching existing code). **Rollback**: Revert thumbnail router. Remove playback route.

---

### Phase 1 Integration Test

Run end-to-end before marking Phase 1 complete:

1. Upload SA key → `POST /api/drive/secrets`
2. Connect Shared Drive → `POST /api/drive/connect`
3. Verify `drive_files` populated → `GET /api/drive/connections/{id}/files`
4. Wait for worker: at least 1 file reaches `indexed` status
5. Search: `POST /api/search/scenes` with `q=` matching the video → results returned with `source_type=gdrive`
6. Playback: `GET /api/drive/playback/{video_id}` → 302 → video streams in browser
7. Thumbnails: verify thumbnails load for Drive-sourced scenes
8. **Regression**: verify agent-ingested videos still search, play, and show thumbnails (unchanged)

---

## Phase 2 — Async HQ Export

### PR 2.1 — Export Job API + Worker Task

**Files to add:**

| Path | Description |
|------|-------------|
| `services/api/app/modules/drive/export_service.py` | Quota check, job creation, status polling |
| `services/drive-worker/src/tasks/export.py` | Download original → ffmpeg cut (fast/precise) → upload S3 → mark completed |
| `services/api/tests/test_drive_exports.py` | Export endpoint tests |
| `services/drive-worker/tests/test_export_task.py` | Export worker task tests |

**Files to modify:**

| Path | Change |
|------|--------|
| `services/api/app/modules/drive/router.py` | Add `POST /api/drive/exports`, `GET /api/drive/exports/{job_id}`, `GET /api/drive/clips/{video_id}` |
| `services/api/app/modules/drive/schemas.py` | Add `ExportRequest`, `ExportResponse`, `ExportStatusResponse`, `ClipRequest` DTOs |
| `services/drive-worker/src/worker.py` | Add `process_pending_exports()` scheduler job (every 30s) |
| `heimdex-media-contracts/.../exports/edl.py` | 1-line change: `src = clip.media_path or clip.media_url` (line ~43) |
| `heimdex-media-contracts/.../exports/fcpxml.py` | 1-line change: asset `src` uses `media_url` fallback (line ~73) |

**Tests:**

| Test | What It Verifies |
|------|-----------------|
| `test_create_export_job` | `POST /api/drive/exports` → 202, job created |
| `test_export_quota_fast` | 31st fast export in 24h → 429 |
| `test_export_quota_precise` | 11th precise export in 24h → 429 |
| `test_export_dedup` | Same (org, user, video, clips, mode) → returns existing job |
| `test_export_status_poll` | `GET /api/drive/exports/{id}` → correct status transitions |
| `test_export_org_isolation` | Org A's export not visible to Org B |
| `test_proxy_clip_stream_copy` | `GET /api/drive/clips/{video_id}?start_ms=X&end_ms=Y` → 302 |
| `test_proxy_clip_max_duration` | >300s → 400 |
| `test_export_fast_mode` | Worker uses `-c copy` for fast mode |
| `test_export_precise_mode` | Worker uses `-c:v libx264 -crf 18` for precise mode |
| `test_export_timeout` | Job >30 min → killed, marked failed |
| `test_edl_media_url_fallback` | EDL uses `media_url` when `media_path` empty |

**Feature flag when disabled**: Export endpoints return 404.

**Security checklist:**
- [ ] Export download URLs expire (24h)
- [ ] Org_id from auth matches job's org_id before returning download URL
- [ ] No Drive credentials in export response

**Operational checklist:**
- [ ] Worker logs: job_id, video_id, mode, duration per step
- [ ] 30 min timeout on export processing
- [ ] Original cached in /tmp during batch (multiple clips from same video)
- [ ] Quota counts returned in response headers (`X-Remaining-Exports-Fast`, `X-Remaining-Exports-Precise`)

**Risk**: Medium. **Rollback**: Remove export endpoints and worker task.

---

### PR 2.2 — S3 Lifecycle + Cleanup

**Files to add:**

| Path | Description |
|------|-------------|
| `services/drive-worker/src/tasks/cleanup.py` | Expired export cleanup: delete S3 objects + mark job `expired` |

**Files to modify:**

| Path | Change |
|------|--------|
| `services/drive-worker/src/worker.py` | Add `cleanup_expired_exports()` scheduler job (daily) |

**Infrastructure:**
- S3 lifecycle rule: `*/exports/*` prefix expires after 1 day
- MinIO: `mc ilm rule add local/heimdex-media --prefix "*/exports/" --expire-days 1`

**Tests:**

| Test | What It Verifies |
|------|-----------------|
| `test_cleanup_expired` | Export >24h old: S3 deleted, status=expired |
| `test_cleanup_active_untouched` | Export <24h old: not cleaned |
| `test_reexport_after_expired` | Re-requesting expired export creates new job |

**Risk**: Low. **Rollback**: Remove cleanup task. S3 lifecycle handles cleanup anyway.

---

## Phase 3 — Delta Sync + Admin UI

### PR 3.1 — Robust Delta Sync + Reconciliation

**Files to add:**

| Path | Description |
|------|-------------|
| `services/drive-worker/src/tasks/reconciliation.py` | Weekly full `files.list`: detect missed changes, orphans, missing S3 |
| `services/drive-worker/tests/test_reconciliation.py` | Reconciliation tests |

**Files to modify:**

| Path | Change |
|------|--------|
| `services/drive-worker/src/tasks/sync.py` | Production-harden: content update → re-process, rename → update OpenSearch, delete → remove scenes + S3 |
| `services/api/app/modules/drive/sync_service.py` | Content update: reset status, delete old proxy, delete old scenes from OpenSearch |
| `services/drive-worker/src/worker.py` | Add `weekly_reconciliation()` scheduler job |

**Tests:**

| Test | What It Verifies |
|------|-----------------|
| `test_content_update` | MD5 change → old scenes removed, file re-processed |
| `test_rename` | Drive rename → file_name updated in DB, video_title updated in OpenSearch |
| `test_delete_trashed` | File trashed → is_deleted=true, scenes removed, proxy deleted from S3 |
| `test_delete_removed` | `removed:true` in change → same as trash |
| `test_move_within_drive` | File moved to different folder → drive_path updated |
| `test_page_token_corruption` | Invalid token → full resync from scratch |
| `test_reconciliation_orphan_db` | File in DB but not in Drive → mark deleted |
| `test_reconciliation_orphan_drive` | File in Drive but not in DB → create pending |
| `test_large_drive_10k_files` | 10,000 files → sync completes without timeout |

**Risk**: Medium-High. **Rollback**: Revert sync changes. Delta sync stops updating but indexed content remains.

---

### PR 3.2 — Admin UI (Drive Connection Management)

**Files to add:**

| Path | Description |
|------|-------------|
| `services/web/src/app/settings/drive/page.tsx` | Drive settings: list connections, connect, disconnect, manual sync |
| `services/web/src/app/settings/drive/connect/page.tsx` | Connection wizard: upload SA key → test → select drive → confirm |
| `services/web/src/app/settings/drive/[id]/page.tsx` | Connection detail: file list with status, sync history, errors |
| `services/web/src/components/DriveFileStatus.tsx` | Status badge: pending/downloading/transcoding/processing/indexing/indexed/failed |

**Files to modify:**

| Path | Change | Exact Location |
|------|--------|---------------|
| `services/web/src/components/SceneThumbnail.tsx` | No change needed — existing cloud fallback already works for Drive thumbnails | N/A |
| `services/web/src/lib/agent.ts` | Add `getProxyPlaybackUrl(videoId)` function returning `/api/drive/playback/${videoId}` | After line 91 |
| `services/web/src/features/shorts/components/SavedShortsPage.tsx` | Conditional routing: `gd_*` → proxy clip, others → agent clip | Lines 152-168 (handleClipDownload) |
| `services/web/src/app/settings/layout.tsx` | Add "Google Drive" to settings sidebar nav | Sidebar links section |

**Tests:**

| Test | What It Verifies |
|------|-----------------|
| `test_drive_settings_page_renders` | Page loads with connection list |
| `test_connect_wizard_flow` | Upload key → test → select → connect |
| `test_file_status_badges` | All 7 states render correctly |
| `test_disconnect_confirmation` | Dialog → API call → removed from list |
| `test_manual_sync_button` | Triggers sync, shows "Syncing..." state |
| `test_korean_ui_text` | All new strings are Korean |
| `test_clip_routing_gdrive` | `gd_*` video uses proxy clip endpoint |
| `test_clip_routing_local` | Non-gd_ video uses agent clip (unchanged) |

**Risk**: Medium. **Rollback**: Remove pages. Revert sidebar nav.

---

### PR 3.3 — Processing Status in Search Results

**Files to modify:**

| Path | Change |
|------|--------|
| `services/api/app/modules/search/service.py` | For `source_type=gdrive` results, enrich with `processing_status` from `drive_files` |
| `services/api/app/modules/search/schemas.py` | Add `processing_status: str | None = None` to `SceneResult` |
| `services/web/src/features/search/components/SearchResults.tsx` | Show "처리 중..." indicator when status != `indexed` |

**Tests:**

| Test | What It Verifies |
|------|-----------------|
| `test_search_enrichment_gdrive` | gdrive results include `processing_status` |
| `test_search_enrichment_local` | Local results have `processing_status=null` (unchanged) |
| `test_search_no_latency_regression` | p95 latency < baseline + 20ms for non-Drive queries |
| `test_ui_processing_indicator` | "처리 중..." shown for non-indexed scenes |

**Risk**: Low-Medium. **Rollback**: Revert enrichment. Search results lose indicator.

---

## Scope Summary

| Phase | PRs | Duration | Risk | LOC Estimate |
|-------|-----|---------|------|-------------|
| 0 — Spike | 0 (throwaway) | 3-5 days | Low | ~200 |
| 1 — Core | 5 PRs | 3-4 weeks | High (PR 1.4) | ~3,000-4,000 |
| 2 — Export | 2 PRs | 2-3 weeks | Medium | ~800-1,200 |
| 3 — Sync + UI | 3 PRs | 2-3 weeks | Medium-High | ~2,000-3,000 |
| **Total** | **10 PRs** | **9-12 weeks** | | **~6,000-8,400** |

## Repos Touched

| Repo | Phase 0 | Phase 1 | Phase 2 | Phase 3 |
|------|---------|---------|---------|---------|
| `dev-heimdex-for-livecommerce` | Scripts | API + Worker | API + Worker | API + Worker + Web |
| `heimdex-media-pipelines` | No | No (read-only mount) | No | No |
| `heimdex-media-contracts` | No | No | 2 one-line changes | No |
| `heimdex-agent` | **No** | **No** | **No** | **No** |

## Execution Order

```
Week 1         : Phase 0 (Spike) → validate Implementation Gate
Week 2-3       : PR 1.1 + PR 1.2 (parallel — no deps between them)
Week 3-4       : PR 1.3 (depends on 1.1 + 1.2)
Week 4-6       : PR 1.4 (hardest PR — extra time)
Week 6         : PR 1.5 + Phase 1 Integration Test
Week 7-8       : PR 2.1 + PR 2.2 (parallel)
Week 8         : Phase 2 Integration Test
Week 9-10      : PR 3.1 + PR 3.2 (parallel — backend sync vs frontend UI)
Week 10-11     : PR 3.3 (depends on 3.1)
Week 11        : Phase 3 Integration Test
Week 12        : Buffer / hardening
```
