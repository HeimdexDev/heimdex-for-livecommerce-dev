# Shorts Render E2E Test Report — 2026-03-25

## Environment

- **Target**: Staging EC2 (`ec2-user@3.34.75.63`)
- **Branch**: `main` (commit `82786d0`)
- **Org ID**: `4d20264c-c440-4d69-8613-7d7558ea386b`
- **Test video**: `gd_c2f4f1d7ca3a6ba3` (260314_닥터포헤어.mp4, 263 scenes, ~4.3min)
- **S3 bucket**: `heimdex-drive-staging`

## Test Scope

End-to-end validation of the shorts rendering pipeline on staging:

1. Worker startup and SQS connectivity
2. Render job creation (DB + SQS publish)
3. Media download from S3
4. FFmpeg clip extraction and composition rendering (CPU)
5. Output upload to S3
6. Status reporting back to API

## Test Input

```json
{
  "title": "E2E Test Short v2",
  "video_id": "gd_c2f4f1d7ca3a6ba3",
  "composition": {
    "output": { "width": 406, "height": 720, "fps": 30, "format": "mp4" },
    "scene_clips": [
      {
        "scene_id": "gd_c2f4f1d7ca3a6ba3_scene_001",
        "video_id": "gd_c2f4f1d7ca3a6ba3",
        "source_type": "gdrive",
        "start_ms": 1300, "end_ms": 5833,
        "timeline_start_ms": 0
      },
      {
        "scene_id": "gd_c2f4f1d7ca3a6ba3_scene_002",
        "video_id": "gd_c2f4f1d7ca3a6ba3",
        "source_type": "gdrive",
        "start_ms": 5833, "end_ms": 8666,
        "timeline_start_ms": 4533
      }
    ],
    "subtitles": [
      {
        "text": "E2E 테스트 자막",
        "start_ms": 0, "end_ms": 3000,
        "style": {
          "font_family": "Noto Sans KR",
          "font_size_px": 20,
          "font_color": "#FFFFFF",
          "font_weight": 700,
          "text_align": "center",
          "position_x": 0.5, "position_y": 0.85
        }
      }
    ]
  }
}
```

## Test Procedure

1. **SSH into staging EC2** via `~/.ssh/heimdex-staging.pem`
2. **Verified infrastructure readiness**:
   - `shorts-render-worker` container running
   - `SQS_SHORTS_RENDER_QUEUE_URL` configured in `.env`
   - DB migrations 036/037 applied (`shorts_render_jobs` table exists)
3. **Identified and fixed blocker**: `MINIO_ENDPOINT=minio:9000` hardcoded in `docker-compose.yml` — worker was trying to use MinIO instead of real AWS S3. Fixed to `${MINIO_ENDPOINT-minio:9000}` (PR #78).
4. **Pulled fix on staging**, rebuilt and restarted `shorts-render-worker`
5. **Found test data** from `drive_files` table and `heimdex_scenes_v4` OpenSearch index
6. **Submitted render job** by inserting DB record + publishing SQS message directly from API container
7. **First attempt failed**: `width: 405` (odd) caused ffmpeg error — `width not divisible by 2 (405x720)`. libx264 requires even dimensions.
8. **Second attempt succeeded** with `width: 406` (even). Full pipeline completed in ~6 seconds.
9. **Verified output**: S3 file exists, DB record has `status=completed` with all metrics.

## Results

| Step | Status | Details |
|---|---|---|
| Worker SQS connectivity | Pass | IAM credentials resolved, consumer started |
| SQS message pickup | Pass | Message received within ~1 second |
| Media download from S3 | Pass | Proxy video downloaded from `heimdex-drive-staging` |
| Clip extraction (ffmpeg) | Pass | 2 clips extracted with frame-accurate seeking |
| Composition render (CPU) | Pass | libx264, preset=medium, crf=23 |
| Korean subtitle overlay | Pass | Noto Sans KR font rendered via drawtext filter |
| S3 upload | Pass | Output at `{org_id}/shorts/renders/{job_id}/output.mp4` |
| DB status update | Pass | `completed`, duration=7366ms, size=529KB, render_time=3587ms |

**Successful job**: `cc221325-e513-4a95-a6c1-2c49450dd1a0`
**S3 output**: `s3://heimdex-drive-staging/4d20264c-c440-4d69-8613-7d7558ea386b/shorts/renders/cc221325-e513-4a95-a6c1-2c49450dd1a0/output.mp4`

## Bugs Found

### 1. MINIO_ENDPOINT hardcoded in docker-compose.yml (Fixed — PR #78)

**File**: `docker-compose.yml:677`
**Symptom**: Worker failed with S3 `HeadObject 404` — connecting to `minio:9000` instead of AWS S3.
**Root cause**: `MINIO_ENDPOINT=minio:9000` was hardcoded unlike all other workers which use `${MINIO_ENDPOINT-minio:9000}`.
**Fix**: Changed to `${MINIO_ENDPOINT-minio:9000}` to respect the `.env` setting (empty on staging = real AWS S3).

### 2. Odd output width causes ffmpeg failure (Fix pending)

**File**: `heimdex-media-contracts/composition/schemas.py`
**Symptom**: `libx264` error: `width not divisible by 2 (405x720)`.
**Root cause**: No validation on `OutputSpec.width`/`height` for even values. The example request body uses `405` (odd).
**Fix**: Added `model_validator` to reject odd dimensions with a clear error message. Needs commit to `heimdex-media-contracts` repo.

### 3. Deploy workflow missing shorts-render-worker (Fixed — PR #78)

**File**: `.github/workflows/deploy-staging.yml`
**Symptom**: Code changes to `services/shorts-render-worker/` were not detected, built, or restarted during staging deploys.
**Fix**: Added `SHORTS_CHANGED` detection, build step, and restart step matching the pattern of other workers.

## Staging IAM Note

The SQS IAM permission for `heimdex-shorts-render-queue` was initially denied (worker logs showed 470 `AccessDenied` errors from 2026-03-23). This was resolved before testing — the `heimdex-staging-ec2` role now has the required `sqs:ReceiveMessage` permission. The worker needed a restart to clear the error state.
