# CPU-only Dockerfile for local development / testing.
# Production: use Dockerfile.gpu on Aircloud+ GPU instances.
FROM python:3.11-slim AS sdk-builder
WORKDIR /build
COPY services/worker_sdk/pyproject.toml .
COPY services/worker_sdk/src/ src/
RUN pip install --no-cache-dir build && python -m build --wheel --outdir /dist

FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV HF_HOME=/models/huggingface

WORKDIR /app

COPY --from=sdk-builder /dist/heimdex_worker_sdk-*.whl /tmp/
RUN pip install --no-cache-dir /tmp/heimdex_worker_sdk-*.whl && rm -f /tmp/*.whl

RUN pip install --no-cache-dir \
      "torch>=2.0" --index-url https://download.pytorch.org/whl/cpu \
    && pip install --no-cache-dir \
      "transformers>=4.49.0" "Pillow>=9.0" \
      "boto3>=1.34" "pydantic-settings>=2.0" \
      "structlog>=23.0" "requests>=2.31"

COPY services/drive-visual-embed-worker/src/ src/

RUN useradd -m -u 1000 appuser \
    && mkdir -p /models && chown -R appuser:appuser /app /models
USER appuser

CMD ["python", "-m", "src.worker"]
