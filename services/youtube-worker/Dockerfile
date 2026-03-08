FROM python:3.11-slim AS sdk-builder
WORKDIR /build
COPY services/worker_sdk/pyproject.toml .
COPY services/worker_sdk/src/ src/
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /dist

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Install deno (required by yt-dlp for YouTube JS challenge processing)
RUN curl -fsSL https://deno.land/install.sh | DENO_INSTALL=/usr/local sh

WORKDIR /app

COPY --from=sdk-builder /dist/heimdex_worker_sdk-*.whl /tmp/
RUN pip install --no-cache-dir /tmp/heimdex_worker_sdk-*.whl && rm -f /tmp/*.whl

COPY services/youtube-worker/pyproject.toml .
RUN pip install --no-cache-dir -e . 2>/dev/null || \
    pip install --no-cache-dir \
      "yt-dlp>=2025.5.0" "bgutil-ytdlp-pot-provider" \
      "requests>=2.31" "boto3>=1.34" \
      "apscheduler>=3.10,<4" "pydantic-settings>=2.0"

COPY services/youtube-worker/src/ src/

RUN useradd -m -u 1000 appuser
USER appuser

CMD ["python", "-m", "src.worker"]
