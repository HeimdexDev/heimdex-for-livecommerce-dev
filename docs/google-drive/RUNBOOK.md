# Runbook: Google Drive Proxy-First Sync

**Date**: 2026-02-19
**Audience**: On-call engineers, DevOps
**Reference**: [ARCHITECTURE.md](./ARCHITECTURE.md)

---

## Setup & Prerequisites

### Google Cloud Project

1. **Create or select** a GCP project
2. **Enable Drive API**: `gcloud services enable drive.googleapis.com`
3. **Create service account**:
   ```bash
   gcloud iam service-accounts create heimdex-drive-sync \
     --display-name="Heimdex Drive Sync" \
     --project=YOUR_PROJECT
   ```
4. **Download JSON key**:
   ```bash
   gcloud iam service-accounts keys create sa-key.json \
     --iam-account=heimdex-drive-sync@YOUR_PROJECT.iam.gserviceaccount.com
   ```

### Domain-Wide Delegation (DWD)

1. Open **Google Workspace Admin Console** → Security → API Controls → Domain-wide delegation
2. Click **Add new** and enter:
   - Client ID: from the service account (numeric, e.g., `1234567890`)
   - Scopes: `https://www.googleapis.com/auth/drive.readonly`
3. **Save** and wait — DWD propagation takes **up to 24 hours**

### Environment Variables

| Variable | Default | Required | Description |
|----------|---------|----------|-------------|
| `DRIVE_CONNECTOR_ENABLED` | `false` | Yes (set `true`) | Master feature flag |
| `DRIVE_ENCRYPTION_KEY` | `""` | Yes | AES-256 key for SA key encryption. Generate: `openssl rand -hex 32` |
| `DRIVE_SYNC_INTERVAL_SECONDS` | `300` | No | Delta sync poll interval (seconds) |
| `DRIVE_MAX_CONCURRENT_DOWNLOADS` | `2` | No | Parallel downloads per worker |
| `DRIVE_MAX_FILE_SIZE_GB` | `10` | No | Skip files larger than this |
| `DRIVE_WORKER_ENABLED` | `true` | No | Worker processing toggle |
| `MINIO_ENDPOINT` | `minio:9000` | Yes | S3/MinIO endpoint |
| `MINIO_ACCESS_KEY` | `heimdex` | Yes | S3 access key |
| `MINIO_SECRET_KEY` | `heimdex_dev_password` | Yes | S3 secret key |
| `MINIO_SECURE` | `false` | No | `true` for AWS S3 |
| `MINIO_BUCKET` | `heimdex-media` | No | Storage bucket name |

### First-Time Setup

```bash
# 1. Run migration (creates 4 new tables, no existing tables modified)
docker exec heimdex-api alembic upgrade head

# 2. Create MinIO bucket (if not exists)
docker exec heimdex-minio mc alias set local http://localhost:9000 heimdex heimdex_dev_password
docker exec heimdex-minio mc mb local/heimdex-media --ignore-existing

# 3. Set S3 lifecycle rule for export cleanup (24h TTL)
docker exec heimdex-minio mc ilm rule add local/heimdex-media \
  --prefix "*/exports/" --expire-days 1

# 4. Start drive worker
docker compose up -d drive-worker
```

---

## Connecting a Shared Drive

### Step 1: Upload Service Account Key

```bash
curl -X POST https://ORGSLUG.app.heimdexdemo.dev/api/drive/secrets \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "service_account_key": '"$(cat sa-key.json)"',
    "impersonate_email": "admin@customer-domain.com"
  }'
```

### Step 2: Test Connection

```bash
curl -X POST https://ORGSLUG.app.heimdexdemo.dev/api/drive/test-connection \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"drive_id": "0AF_SHARED_DRIVE_ID"}'

# Expected: {"status": "ok", "drive_name": "라이브커머스 영상", "files_count": 42}
# If error: check DWD setup, wait up to 24h for propagation
```

### Step 3: Connect the Drive

```bash
curl -X POST https://ORGSLUG.app.heimdexdemo.dev/api/drive/connect \
  -H "Authorization: Bearer $JWT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "drive_id": "0AF_SHARED_DRIVE_ID",
    "library_id": "LIBRARY_UUID"
  }'
```

### Step 4: Verify File Discovery

```bash
curl https://ORGSLUG.app.heimdexdemo.dev/api/drive/connections/{CONNECTION_ID}/files \
  -H "Authorization: Bearer $JWT_TOKEN"

# Should show files with processing_status: "pending"
```

---

## Monitoring

### Worker Health

```bash
# Live logs
docker logs heimdex-drive-worker --tail 100 -f

# Check if worker is running
docker ps --filter name=heimdex-drive-worker --format "table {{.Status}}\t{{.RunningFor}}"
```

### Connection Status

```sql
SELECT
  dc.drive_name,
  dc.status,
  dc.last_sync_at,
  dc.error_message,
  COUNT(df.id) AS total_files,
  COUNT(df.id) FILTER (WHERE df.processing_status = 'indexed') AS indexed,
  COUNT(df.id) FILTER (WHERE df.processing_status = 'pending') AS pending,
  COUNT(df.id) FILTER (WHERE df.processing_status = 'failed') AS failed
FROM drive_connections dc
LEFT JOIN drive_files df ON df.connection_id = dc.id
WHERE dc.org_id = 'ORG_UUID'
GROUP BY dc.id;
```

### Processing Queue Depth

```sql
SELECT processing_status, COUNT(*)
FROM drive_files
WHERE org_id = 'ORG_UUID'
GROUP BY processing_status
ORDER BY COUNT(*) DESC;
```

### Failed Files

```sql
SELECT file_name, processing_status, last_error, retry_count, last_attempt_at
FROM drive_files
WHERE org_id = 'ORG_UUID'
  AND processing_status = 'failed'
ORDER BY last_attempt_at DESC;
```

### S3 Storage Usage

```bash
# MinIO (dev)
docker exec heimdex-minio mc du local/heimdex-media/ORG_UUID/drive/

# AWS S3 (production)
aws s3 ls s3://heimdex-media/ORG_UUID/drive/ --recursive --summarize | tail -2
```

### Export Queue

```sql
SELECT status, COUNT(*), AVG(EXTRACT(EPOCH FROM (completed_at - created_at))) AS avg_seconds
FROM drive_export_jobs
WHERE created_at > now() - interval '24 hours'
GROUP BY status;
```

---

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|-------------|-----|
| "Connection test failed" | DWD not propagated yet (takes up to 24h) or wrong scope | Check Google Admin Console > API Controls > DWD. Verify scope is `drive.readonly`. Wait 24h, retry. |
| Files stuck in `pending` | Worker not running or overloaded | `docker restart heimdex-drive-worker`. Check `docker logs`. Verify `DRIVE_WORKER_ENABLED=true`. |
| Files stuck in `downloading` | Drive API rate limit (403/429) or file too large | Check worker logs for HTTP status. Verify `DRIVE_MAX_FILE_SIZE_GB`. Reduce `DRIVE_MAX_CONCURRENT_DOWNLOADS` to 1. |
| Files stuck in `transcoding` | ffmpeg crash or hang on corrupt video | Check worker logs for ffmpeg stderr. Run `ffprobe /tmp/drive-processing/{file_id}/original.mp4` inside worker container to inspect file. |
| Search returns video but playback 404 | Proxy not yet in S3 (still processing) | Check `drive_files.processing_status`. Wait for `indexed` status. |
| Thumbnails missing for Drive videos | S3 upload failed during processing | Check `drive_files.thumbnail_s3_prefix`. Re-process: `UPDATE drive_files SET processing_status='pending' WHERE video_id='gd_...'`. |
| Export says "Original no longer available" | File deleted from Google Drive | Nothing to do — original is gone. Proxy still works for preview playback. |
| All syncs failing for one org | DWD revoked, SA key rotated, or Shared Drive deleted | Re-upload SA key via `/api/drive/secrets`. Re-test connection. |
| Worker OOM killed | Too many concurrent downloads or large file | `docker stats heimdex-drive-worker`. Reduce `DRIVE_MAX_CONCURRENT_DOWNLOADS=1`. Reduce `DRIVE_MAX_FILE_SIZE_GB=5`. |
| Stale processing (>30 min) | Worker crashed mid-processing | Worker auto-resets stale jobs on startup. Or manually: see "Reset Stuck Files" below. |
| Search returns duplicate scenes | Worker re-indexed without deleting old scenes | Scenes are idempotent (OpenSearch `_id` = `org_id:scene_id`). Re-index overwrites. Not a real duplicate. |
| Wrong video title in search | Drive file renamed but OpenSearch not updated | Delta sync handles renames. If missed: trigger manual sync via `POST /api/drive/connections/{id}/sync`. |

---

## Emergency Procedures

### Disable Drive Sync Immediately

```bash
# Stop the worker (safest — no in-progress jobs affected)
docker stop heimdex-drive-worker

# Or: disable via feature flag (API endpoints return 404)
# Requires API restart to pick up env change
docker exec heimdex-api bash -c "echo 'DRIVE_CONNECTOR_ENABLED=false' >> .env"
docker restart heimdex-api
```

### Reset Stuck Files

```sql
-- Reset files stuck in transient states for >30 minutes
UPDATE drive_files
SET processing_status = 'pending',
    retry_count = retry_count + 1,
    last_error = 'Manual reset: stuck in ' || processing_status
WHERE processing_status IN ('downloading', 'transcoding', 'processing', 'indexing')
  AND last_attempt_at < now() - interval '30 minutes';
```

### Force Full Resync for a Connection

```sql
-- Wipe change token → next sync does full files.list
UPDATE drive_connections
SET change_token = NULL,
    last_sync_at = NULL
WHERE id = 'CONNECTION_UUID';

-- Restart worker to pick up immediately
docker restart heimdex-drive-worker
```

### Rollback Database Migration

```bash
# WARNING: This drops ALL drive_* tables and ALL data in them
# Export data first if needed
docker exec heimdex-api alembic downgrade 011
```

### Clean S3 Data for an Org

```bash
# MinIO (dev)
docker exec heimdex-minio mc rm --recursive --force local/heimdex-media/ORG_UUID/drive/
docker exec heimdex-minio mc rm --recursive --force local/heimdex-media/ORG_UUID/exports/

# AWS S3 (production)
aws s3 rm s3://heimdex-media/ORG_UUID/drive/ --recursive
aws s3 rm s3://heimdex-media/ORG_UUID/exports/ --recursive
```

### Wipe and Reprocess a Single File

```sql
-- 1. Delete scenes from OpenSearch (via API or direct)
-- curl -X POST https://ORGSLUG.app.heimdexdemo.dev/opensearch/heimdex_scenes_v1/_delete_by_query \
--   -d '{"query":{"term":{"video_id":"gd_abc123"}}}'

-- 2. Delete S3 objects
-- mc rm --recursive local/heimdex-media/ORG_UUID/drive/DRIVE_ID/GOOGLE_FILE_ID/

-- 3. Reset file to pending
UPDATE drive_files
SET processing_status = 'pending',
    retry_count = 0,
    proxy_s3_key = NULL,
    thumbnail_s3_prefix = NULL,
    scene_count = 0,
    last_error = NULL
WHERE video_id = 'gd_abc123';
```

---

## Capacity Planning

### Storage

| Scale | Proxy Storage | Monthly Cost (S3 Standard, ap-northeast-2) |
|-------|--------------|---------------------------------------------|
| 100 videos x 150 MB | 15 GB | ~$0.35 |
| 500 videos x 150 MB | 75 GB | ~$1.75 |
| 2,000 videos x 150 MB | 300 GB | ~$6.90 |
| 10,000 videos x 150 MB | 1.5 TB | ~$34.50 |

Thumbnail storage: negligible (~500 KB per video, ~5 scenes x 100 KB).

### Compute

| Instance | vCPU | RAM | Use Case | Monthly Cost |
|----------|------|-----|----------|-------------|
| t3.medium | 2 | 4 GB | Steady state (1-5 new videos/day) | ~$30 |
| c5.xlarge | 4 | 8 GB | Initial backfill (100+ videos) | ~$122 |
| c5.2xlarge | 8 | 16 GB | Heavy backfill (500+ videos) | ~$245 |

### Processing Time Estimates

| Operation | Duration |
|-----------|---------|
| Download 1 GB from Drive | ~10-20s @ 50-100 MB/s |
| Transcode 30 min 1080p → 720p proxy | ~5-10 min (2 cores, CRF 23 fast) |
| Scene detection + keyframe extraction | ~1-2 min |
| STT (faster-whisper, 30 min audio) | ~3-5 min |
| OCR (original-res keyframes, ~5 scenes) | ~30-60s |
| Upload proxy + thumbnails to S3 | ~5-10s |
| Full pipeline per video (30 min) | ~15-25 min |
| Initial backfill: 500 videos | ~5-9 days (sequential, 1 worker) |
| Initial backfill: 500 videos | ~1.5-2.5 days (4 concurrent, 4-core instance) |

### Temp Disk Requirements

| Scenario | Disk Needed |
|----------|-----------|
| 1 concurrent video (3 GB original) | ~4.5 GB |
| 2 concurrent videos (3 GB each) | ~9 GB |
| 1 large video (10 GB original) | ~11.5 GB |

The `tmpfs` in docker-compose is set to 20 GB. For initial backfill with large files, consider mounting an SSD volume instead of tmpfs.

---

## Alert Thresholds (Recommended)

| Alert | Trigger | Severity |
|-------|---------|---------|
| Worker container not running | Health check fails 3x | High |
| >10 files in `failed` status for one org | DB query (cron every 15 min) | Medium |
| Connection in `error` status | DB query | Medium |
| S3 disk > 80% capacity | MinIO/CloudWatch metric | High |
| Export job pending > 1 hour | DB query | Low |
| No sync activity for active connection > 24h | `last_sync_at` check | Medium |
| Worker memory > 80% | `docker stats` / cAdvisor | Medium |
