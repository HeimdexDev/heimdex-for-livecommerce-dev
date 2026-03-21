# ── Stage 1: Build worker SDK wheel ──────────────────────────────
FROM python:3.11-slim AS sdk-builder
WORKDIR /build
COPY services/worker_sdk/pyproject.toml .
COPY services/worker_sdk/src/ src/
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /dist

# ── Stage 2: Runtime ─────────────────────────────────────────────
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Install ffmpeg (system package — works on both amd64 and arm64)
# Production GPU builds use BtbN static ffmpeg 7.x in Dockerfile.gpu
RUN apt-get update && apt-get install -y --no-install-recommends \
      ffmpeg fontconfig \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install worker SDK
COPY --from=sdk-builder /dist/heimdex_worker_sdk-*.whl /tmp/
RUN pip install --no-cache-dir /tmp/heimdex_worker_sdk-*.whl && rm -f /tmp/*.whl

# Install Python dependencies.
# heimdex-media-contracts + heimdex-media-pipelines are volume-mounted
# in local dev (docker-compose) and pip-installed in CI/prod builds.
RUN pip install --no-cache-dir \
      "boto3>=1.34" "pydantic-settings>=2.0" \
      "structlog>=23.0" "requests>=2.31" "pydantic>=2.0"

# Bundle Korean fonts (Task 10)
COPY services/shorts-render-worker/fonts/ /usr/share/fonts/heimdex/
COPY services/shorts-render-worker/fonts.conf /etc/fonts/conf.d/99-heimdex.conf
RUN fc-cache -f -v

# Copy worker source
COPY services/shorts-render-worker/src/ src/

# Create work directory and non-root user
RUN mkdir -p /data \
    && useradd -m -u 1000 appuser \
    && chown -R appuser:appuser /app /data

# Note: USER appuser is set in Dockerfile.gpu for production.
# For local dev (docker-compose), the startup command needs root for pip install.
CMD ["python", "-m", "src.worker"]
