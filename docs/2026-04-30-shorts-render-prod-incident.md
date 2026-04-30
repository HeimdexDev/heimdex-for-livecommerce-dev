# 2026-04-30 — ebsdemo "Failed to enqueue render job" outage

## Symptom

ebsdemo customers reported every rough-cut render attempt on
`https://ebsdemo.app.heimdex.co/export/preedit` ending with a toast reading

> Failed to enqueue render job

The full reproduction was:

1. Open `/export/preedit`
2. Add clips to the timeline
3. Click "Start render"
4. Toast appears within ~1 second; UI flips to "failed"

The failure was masked at the HTTP layer: `POST /api/shorts/render` returned
**201 Created** with a JSON body containing `status: "failed"`. The frontend
then surfaced the body's `error` field to the user. HTTP-level monitoring
(5xx alerts, dashboards) did not fire.

The customer report was the first signal. No other surface (drive sync,
search, image search, image download) was affected.

## Investigation findings (in order)

Detective trail from the api logs:

```
{"event": "render_job_created", "job_id": "0dd8a393-cc16-4a78-bb73-c3b185590899", ...,
 "request_id": "41f51ac9-968a-47db-b47e-90c04eb0950c", "level": "info",
 "logger": "app.modules.shorts_render.service", "timestamp": "2026-04-29T16:24:56.398812Z"}
{"event": "sqs_shorts_render_publish_failed", "level": "error", ...,
 "exception": "Traceback ...
   File \"/app/app/modules/shorts_render/service.py\", line 344, in create_render_job
     publish_shorts_render_job(...)
   File \"/app/app/sqs_producer.py\", line 799, in publish_shorts_render_job
     raise RuntimeError(\"SQS_SHORTS_RENDER_QUEUE_URL is not configured\")
 RuntimeError: SQS_SHORTS_RENDER_QUEUE_URL is not configured"}
```

The producer raise is caught at `services/api/app/modules/shorts_render/service.py:350-358`,
which flips the DB row to `status='failed'` with `error="Failed to enqueue
render job"`. That string reaches the user verbatim.

Database confirmed exactly one ebsdemo render in seven days, status `failed`,
created at `2026-04-29 16:24 UTC`. SQS queue depth on
`heimdex-shorts-render-queue`: 0. DLQ: 0.

## Root causes — three compounding gaps

### 1. `SQS_SHORTS_RENDER_QUEUE_URL` missing from prod `.env`

The api and worker compose entries (`docker-compose.yml:179, 802`) both
reference the queue URL with the empty-default pattern:

```yaml
- SQS_SHORTS_RENDER_QUEUE_URL=${SQS_SHORTS_RENDER_QUEUE_URL:-}
```

Prod `.env` (216 lines, all other `SQS_*_QUEUE_URL=...` entries present)
did not have this var. The empty default silenced the missing config — the
api booted and served traffic for weeks before the first render attempt
revealed the gap. There is no startup-time assertion in `app/sqs_producer.py`
that would fail-fast if a publisher's queue URL is empty; the check only
fires when `publish_shorts_render_job` is actually called.

### 2. `shorts-render-worker` never brought up on prod

`docker compose ps` did not list the worker. `docker ps -a --filter
name=shorts-render` was empty. No image was built.

This worker is **not in the GitHub Actions deploy workflow's `services`
list** (`.github/workflows/deploy-prod.yml`) — same as
`drive-blur-worker`, `drive-reranker-worker`, `drive-{transcode,stt,ocr,
face,visual-embed,caption}-worker`, and `llama-caption-server`. Bringup
on prod requires SSH-driven `docker compose build` + `up`. This was a
known follow-up (per memory `project_composition_fonts.md` 2026-04-29,
"shorts-render-worker still on old image, manual SSH rebuild pending"),
but the actual gap was harsher: not "old image", literally never built.

### 3. IAM `SQSAccess` policy scoped to `livenow-*` only

`livenow-prod-ec2-role`'s inline `SQSAccess` policy:

```json
"Resource": "arn:aws:sqs:ap-northeast-2:752198711321:livenow-*"
```

This wildcard does not match `heimdex-shorts-render-queue` /
`heimdex-shorts-render-dlq`. Without the ARN match, every
`sqs:ReceiveMessage` (worker) and `sqs:SendMessage` (api) returns
`AccessDenied` — even with the env var correctly set and the worker
container running.

The same prefix mismatch applies to:

| Queue | Feature | Live on prod? |
|---|---|---|
| `heimdex-blur-queue` / -dlq | PII blur | No (`BLUR_ENABLED=false`) |
| `heimdex-product-enumerate-queue` / -dlq | Auto-shorts product v2 | No (`AUTO_SHORTS_PRODUCT_V2_ENABLED=false`) |
| `heimdex-product-track-queue` / -dlq | Auto-shorts Phase 3 | No (not built) |

Each will surface as a fresh `AccessDenied` outage the moment its feature
flag is flipped. Audit + add ARNs in the same change-set as the flag flip.

## Fix sequence (applied 2026-04-30 ~10:35–10:42 UTC)

```bash
# --- on prod EC2 (54.116.79.254 via EC2 Instance Connect) ---

cd /opt/heimdex/dev-heimdex-for-livecommerce

# 1. Snapshot .env + append the missing var
cp .env .env.bak.20260430_103530
cat >> .env <<'EOF'

# Added 2026-04-30: ebsdemo render incident — see docs/2026-04-30-shorts-render-prod-incident.md
SQS_SHORTS_RENDER_QUEUE_URL=https://sqs.ap-northeast-2.amazonaws.com/752198711321/heimdex-shorts-render-queue
EOF

# 2. Recreate api so it picks up the new var (~30s downtime)
docker compose up -d --no-deps api

# 3. Build + start the worker
nohup setsid docker compose build shorts-render-worker > /tmp/srw-build.log 2>&1 < /dev/null &
# (wait ~5 min for build)
docker compose up -d --no-deps shorts-render-worker
```

```bash
# --- locally (IAM update via AWS CLI) ---

aws iam get-role-policy --role-name livenow-prod-ec2-role --policy-name SQSAccess > /tmp/sqs-current.json

# Edit the Resource list to add the two ARNs (preserve livenow-*):
# "Resource": [
#   "arn:aws:sqs:ap-northeast-2:752198711321:livenow-*",
#   "arn:aws:sqs:ap-northeast-2:752198711321:heimdex-shorts-render-queue",
#   "arn:aws:sqs:ap-northeast-2:752198711321:heimdex-shorts-render-dlq"
# ]

aws iam put-role-policy --role-name livenow-prod-ec2-role --policy-name SQSAccess \
  --policy-document file:///tmp/sqs-access-policy.json
```

```bash
# --- on prod EC2 again ---

# 4. Restart the worker so boto3 fetches fresh creds. Without this it
#    keeps emitting AccessDenied for ~6h until the cached STS token rotates.
docker compose restart shorts-render-worker
```

## Verification

- `aws sqs get-queue-attributes` on both `heimdex-shorts-render-queue`
  and `heimdex-shorts-render-dlq` returned 0 messages, 0 in-flight.
- Worker logs after restart showed `font_dir_verified`,
  `sqs_consumer_started`, `shorts_render_worker_started`, no
  `AccessDenied` for 30+ seconds.
- API container env confirmed populated:
  `docker compose exec -T api sh -c 'echo $SQS_SHORTS_RENDER_QUEUE_URL'`
  → `https://sqs.ap-northeast-2.amazonaws.com/752198711321/heimdex-shorts-render-queue`.

End-to-end customer validation pending — next ebsdemo render attempt is
the live test.

## Followups

- **IAM latent gaps** for blur, product-enumerate, product-track — see
  the table in root cause #3. Add ARNs in the same PR as each feature's
  prod enablement.
- **`shorts-render-worker` not in deploy workflow's `services` list**.
  Either (a) add it (and the other excluded workers) to
  `.github/workflows/deploy-prod.yml` so they redeploy automatically,
  or (b) add a smoke test that asserts the worker is `Up` after every
  prod deploy. (a) is harder because workers need GPU/model rebuilds
  with longer timeouts; (b) is cheaper but only catches the regression
  after it ships.
- **Startup-time assertion in `app/sqs_producer.py`** — fail-fast on
  empty queue URL during app boot for any SQS publisher that the api
  actually uses (gated by feature flags / route registration). Beats
  the current "fail at first request" pattern that took weeks to
  surface.
- **Consider returning a non-2xx status from `POST /api/shorts/render`
  when the publish fails synchronously**. Today it returns 201 with
  `status="failed"` in the body. A `502 Bad Gateway` or similar would
  let HTTP-level monitoring catch this without the frontend having
  to parse the response body. (Trade-off: the row IS created, so 201
  is technically accurate; semantic argument for returning 500-ish on
  enqueue failure is stronger than HTTP-spec purity here.)

## Related memory

- `project_composition_fonts.md` — flagged worker rebuild as pending
- `project_prod_iam_blur_queue_gap.md` — same root cause pattern
  (livenow-* prefix), updated post-fix to include the broader audit
- `project_ebsdemo_render_incident_2026_04_30.md` — auto-memory
  capturing the full incident
