# drive-blur-worker

User-triggered PII blur for Heimdex video assets. Consumes
`heimdex-blur-queue`, runs face + OWLv2 detection on the proxy mp4 via
`heimdex_media_pipelines.blur`, uploads a blurred copy + manifest to S3,
and reports back to the API. Off by default behind `BLUR_ENABLED=false`.

## Architecture at a glance

```
User
  │ POST /api/blur/videos/{file_id}     {options}
  ▼
API ── creates blur_jobs row (status=queued)
   ── publishes blur.job_created → heimdex-blur-queue
   ── returns 202 {job_id}

heimdex-blur-queue
  │ (Aircloud GPU worker wakes via gpu_orchestrator)
  ▼
drive-blur-worker
  ── POST /internal/blur/{job_id}/claim         queued → running, lease_token
  ── S3 GET  proxies/{video_id}/proxy.mp4
  ── BlurPipeline.process_video (face + OWLv2)
  ── S3 PUT  blurred/{video_id}/{job_id}/blurred.mp4
  ── S3 PUT  blurred/{video_id}/{job_id}/manifest.json
  ── POST /internal/blur/{job_id}/complete      running → done

User
  │ GET /api/blur/jobs/{job_id}
  ▼
API ── returns status, blurred_s3_key, manifest_s3_key, detections_summary
```

`drive-blur-worker` is fully decoupled from the transcode / enrichment /
indexing pipeline. Nothing downstream reacts to blur completion. Killing
the worker has zero effect on existing video processing.

## Environment variables

All settings live in `WorkerSettings` (`heimdex-worker-sdk`) — set them
on the Aircloud endpoint or in `.env` for local dev.

| Var | Default | Purpose |
|---|---|---|
| `BLUR_ENABLED` | `false` | Global kill switch. Worker refuses to start while false. |
| `SQS_CONSUMER_ENABLED` | `false` | Must be `true` for the worker to poll SQS. |
| `SQS_BLUR_QUEUE_URL` | `""` | `https://sqs.ap-northeast-2.amazonaws.com/752198711321/heimdex-blur-queue` |
| `SQS_REGION` | `ap-northeast-2` | |
| `DRIVE_API_BASE_URL` | `http://api:8000` | Internal API for `/internal/blur/*` callbacks. |
| `DRIVE_INTERNAL_API_KEY` | `""` | Pre-shared secret for `verify_internal_token`. Same value as other workers. |
| `DRIVE_S3_BUCKET` | `heimdex-drive` | |
| `S3_REGION` | `ap-northeast-2` | |
| `USE_GPU` | `false` | Set `true` on Aircloud — selects CUDA execution provider. |
| `BLUR_ALLOW_CPU` | `false` | **Dev/test only.** Worker refuses to start without a GPU unless this is `true`. |
| `BLUR_OWL_MODEL` | `google/owlv2-base-patch16-ensemble` | HuggingFace model id. **Override here to swap models without rebuilding the container** (e.g. `google/owlv2-large-patch14` once it's been validated against the fixture sweep). |
| `BLUR_OWL_STRIDE` | `5` | Run OWLv2 every Nth frame; cached in between. Higher = faster, looser. |
| `BLUR_OWL_SCORE_THRESHOLD` | `0.35` | Per-detection confidence floor. |
| `DRIVE_BLUR_CONCURRENCY` | `1` | Per-process job concurrency. **Keep at 1** — OWLv2 saturates an L4/A10. |
| `BLUR_LEASE_SECONDS` | `1800` | Worker lease + SQS visibility timeout (30 min). |
| `HF_HOME` | `/models/hf` | HuggingFace cache; mount as a volume to skip cold-start downloads. |
| `LOG_LEVEL` | `INFO` | |

API-side settings (set on the API container, not here):

| Var | Default | Purpose |
|---|---|---|
| `BLUR_ENABLED` | `false` | Same flag, also gates the `/api/blur/*` router. |
| `SQS_BLUR_QUEUE_URL` | `""` | Producer side. |
| `AIRCLOUD_ENDPOINT_BLUR` | `""` | Aircloud endpoint UUID for `gpu_orchestrator.ensure_worker_running("blur")`. |
| `BLUR_MAX_ACTIVE_PER_ORG` | `5` | Concurrency cap (queued + running). 429 on excess. |
| `BLUR_LEASE_SECONDS` | `1800` | Must match worker. |
| `BLUR_DAILY_BUDGET_USD_PER_ORG` | `50.0` | Reserved for circuit breaker (not yet wired). |

## Local development

The worker is gated behind a docker-compose profile so day-to-day
`docker compose up` ignores it.

```bash
# From repo root.
docker compose --profile blur up --build drive-blur-worker

# With BLUR_ALLOW_CPU=true so the worker boots without a GPU.
BLUR_ENABLED=true \
BLUR_ALLOW_CPU=true \
SQS_CONSUMER_ENABLED=true \
SQS_BLUR_QUEUE_URL=https://sqs.ap-northeast-2.amazonaws.com/752198711321/heimdex-blur-queue \
docker compose --profile blur up --build drive-blur-worker
```

The compose entry mounts `heimdex-media-contracts`, `heimdex-media-pipelines`,
and `heimdex-worker-sdk` from sibling checkouts as editable installs, so
local edits in those repos hot-reload on the next worker restart without
rebuilding the image.

## CI image build

GitHub Actions builds `ghcr.io/jlee-heimdex/heimdex-blur-worker-gpu`
from `Dockerfile.gpu` on:

* every push to `main` that touches `services/drive-blur-worker/**`
* manual trigger via `gh workflow run build-gpu-images.yml -f workers=blur`

Tags published:
* `ghcr.io/jlee-heimdex/heimdex-blur-worker-gpu:latest`
* `ghcr.io/jlee-heimdex/heimdex-blur-worker-gpu:<commit-sha>` ← pin Aircloud at this

First build is 15–20 min (torch cu124 + transformers + OWLv2 weight
pre-warm + SCRFD weight pre-warm). Subsequent builds reuse the GHA layer
cache and finish in ~3 min.

## Aircloud endpoint provisioning

Once `:gpu-<sha>` is on GHCR:

1. Aircloud console → **New endpoint** → name `heimdex-blur-gpu`
2. Image: `ghcr.io/jlee-heimdex/heimdex-blur-worker-gpu:<sha>`
3. GPU tier: ≥ 8 GB VRAM (L4 / A10, same as `heimdex-face-gpu`)
4. Env passthrough — copy the worker side of the table above. **Required**:
   * `BLUR_ENABLED=true`
   * `SQS_CONSUMER_ENABLED=true`
   * `SQS_BLUR_QUEUE_URL=https://sqs.ap-northeast-2.amazonaws.com/752198711321/heimdex-blur-queue`
   * `DRIVE_API_BASE_URL=https://<staging-internal-api-url>`
   * `DRIVE_INTERNAL_API_KEY=<same secret as face worker>`
   * `DRIVE_S3_BUCKET=heimdex-drive`
   * `S3_REGION=ap-northeast-2`
   * `USE_GPU=true`
   * `BLUR_ALLOW_CPU=false`
5. AWS credentials: IAM role or env vars, same pattern as face worker
6. Capture the endpoint UUID — that's `AIRCLOUD_ENDPOINT_BLUR` for the API

## Staging enable

Three env vars on the staging API container:

```bash
BLUR_ENABLED=true
SQS_BLUR_QUEUE_URL=https://sqs.ap-northeast-2.amazonaws.com/752198711321/heimdex-blur-queue
AIRCLOUD_ENDPOINT_BLUR=<uuid from Aircloud>
```

Trigger the staging deploy and verify the API container has the new
values:

```bash
ssh -i ~/.ssh/heimdex-staging.pem ec2-user@3.34.75.63
docker compose exec api env | grep BLUR
docker compose exec api curl -s http://localhost:8000/api/blur/jobs/00000000-0000-0000-0000-000000000000 -H "Authorization: Bearer ..." | jq
# Expect 404 (job not found, but the route is reachable — proves BLUR_ENABLED=true)
```

## Smoke test (single video end-to-end)

After the staging API is on, push a known sample through:

```bash
# Pick a known file_id and user that has blur:create scope.
FILE_ID=...
TOKEN=...

curl -X POST https://devorg.app.heimdexdemo.dev/api/blur/videos/$FILE_ID \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
# → 202 {"id": "...", "status": "queued"}

JOB_ID=...
watch -n 5 "curl -s https://devorg.app.heimdexdemo.dev/api/blur/jobs/$JOB_ID \
  -H 'Authorization: Bearer $TOKEN' | jq '{status, blurred_s3_key, error}'"
# Expect: queued → running → done within minutes
```

When status flips to `done`:

```bash
aws s3 ls "s3://heimdex-drive/blurred/<video_id>/$JOB_ID/"
aws s3 cp "s3://heimdex-drive/blurred/<video_id>/$JOB_ID/manifest.json" - | jq .summary
```

## Fixture regression sweep

Reproduce 효정님's reference outputs against the live worker to confirm
parity. The script lives in the pipelines repo, not this worker:

```bash
cd ../../../heimdex-media-pipelines
SAMPLES_DIR=/path/to/blur_owl_pipeline/samples \
OUT_DIR=/tmp/blur-fixture-sweep \
scripts/blur-fixture-sweep.sh
```

Each video produces `OUT_DIR/<stem>/<stem>_blurred_owl.mp4` +
`<stem>_manifest.json` matching her original tree layout. Diff the
mp4s + manifests against the reference set in
`s3://heimdex-qa/blur-fixtures/`. Any drift = pin mismatch in
`requirements.txt` to investigate before flipping more tenants.

## Cancel / cleanup

```bash
# Cancel a queued job (no effect once running).
curl -X POST https://devorg.app.heimdexdemo.dev/api/blur/jobs/$JOB_ID/cancel \
  -H "Authorization: Bearer $TOKEN"

# Tear down a terminal job + its S3 outputs.
curl -X DELETE https://devorg.app.heimdexdemo.dev/api/blur/jobs/$JOB_ID \
  -H "Authorization: Bearer $TOKEN"
```

## DLQ inspection

Failed jobs land in `heimdex-blur-dlq` after 3 receive attempts.

```bash
aws sqs get-queue-attributes \
  --region ap-northeast-2 \
  --queue-url https://sqs.ap-northeast-2.amazonaws.com/752198711321/heimdex-blur-dlq \
  --attribute-names ApproximateNumberOfMessages

aws sqs receive-message \
  --region ap-northeast-2 \
  --queue-url https://sqs.ap-northeast-2.amazonaws.com/752198711321/heimdex-blur-dlq \
  --max-number-of-messages 10
```

If a message is in the DLQ, the corresponding `blur_jobs` row is in
`status='failed'` (or stuck `running` with an expired lease, depending
on where it died). Inspect the row, then either delete the message
(give up) or send it back to the main queue (manual replay).

## Switching the OWLv2 model without a redeploy

Per 효정님's request, the model is a worker-level env var, not baked
into the image. To swap:

1. Set `BLUR_OWL_MODEL=google/owlv2-large-patch14` (or any HF-compatible OWLv2 id) on the Aircloud endpoint
2. Restart the container (Aircloud "Restart" button or stop → start cycle)
3. Worker boots, downloads the new weights to `HF_HOME`, warms them, resumes consuming SQS

No code change. No rebuild. The previous run's manifests still validate
because `owl_model` lives in the untyped `config` blob, not a typed
contracts field.

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| Worker exits with `blur_worker_refusing_to_start  reason=BLUR_ENABLED is false` | Global kill switch is off | Set `BLUR_ENABLED=true` |
| Worker exits with `blur_worker_refusing_cpu_mode` | No CUDA device + `BLUR_ALLOW_CPU=false` | Provision a GPU host, or set `BLUR_ALLOW_CPU=true` for dev only |
| Worker exits with `sqs_consumer_required_but_not_configured queue=blur` | Missing queue URL or consumer flag | Set `SQS_CONSUMER_ENABLED=true` and `SQS_BLUR_QUEUE_URL=...` |
| `POST /api/blur/videos/{id}` returns 404 | API has `BLUR_ENABLED=false` or the file doesn't exist | Check API env; verify the file_id with the drive endpoint |
| `POST /api/blur/videos/{id}` returns 409 with "no proxy yet" | Transcode hasn't completed | Wait for status `indexed`, then retry |
| `POST /api/blur/videos/{id}` returns 429 "Too many active blur jobs" | Org has 5 jobs in flight | Wait or cancel queued jobs |
| `POST /api/blur/videos/{id}` returns 429 "Blur submission rate limit exceeded" | User has used 10 submissions in the past hour | Wait |
| Job stuck in `queued` for minutes | Aircloud endpoint cold-starting OR `AIRCLOUD_ENDPOINT_BLUR` unset on API | Check Aircloud console; verify the API env var |
| Job in `running` for > 30 minutes | Stale lease — worker died | Lease expires; SQS redelivers; new worker takes over. If lease keeps expiring → check OWLv2 OOMs in worker logs |
| Cancel returns 409 "too late to cancel" | Worker claimed the job between your read and the API's update | Job will run to completion; delete the output afterward |
| Manifest much smaller than expected | Stride too high, threshold too high, or the video genuinely has nothing to blur | Tune `owl_stride` / `score_threshold` per request via `BlurOptions` |

## Code map

```
services/drive-blur-worker/
├── Dockerfile.gpu                # CUDA 12.4 + torch 2.4.1 + transformers
├── requirements.txt              # 효정님의 검증된 핀
├── .dockerignore
├── README.md                     # this file
├── src/
│   ├── worker.py                 # SQSConsumerLoop boot, BlurPipeline warm-up
│   └── tasks/
│       └── blur_video.py         # claim → download → run → upload → complete
└── tests/
    └── test_blur_video.py        # stubbed pipeline + mocked HTTP/S3
```

The runtime library is in `heimdex-media-pipelines/src/heimdex_media_pipelines/blur/`:
`primitives.py`, `queries.py`, `owlv2.py`, `pipeline.py`, `cli.py`,
`config.py`. The HTTP contract is in
`heimdex-media-contracts/src/heimdex_media_contracts/blur/schemas.py`.
The API side lives in `services/api/app/modules/blur/`.

## Anti-patterns

* **Never** import from `app.*` in this worker — internal HTTP only via
  `requests` to `/internal/blur/*`. Coupling-check CI enforces this.
* **Never** add a per-request `owl_model` override in `BlurOptions` —
  switching mid-process means reloading 400 MB of weights and defeats
  the warmed pipeline. Use the worker-level env var instead.
* **Never** loosen `requirements.txt` pins independently — torch /
  transformers / insightface / opencv were validated together against
  효정님's sample set. Bump in lockstep.
* **Never** widen `_apply_options_to_pipeline`'s allow-list to include
  model / device / face-detector fields. Tests assert on the current
  set; CI catches drift.
* **Never** delete a `blur_jobs` row from a worker — the worker only
  POSTs to `/internal/blur/{id}/complete`. DB writes belong to the API.
