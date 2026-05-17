FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

RUN pip install --no-cache-dir "heimdex-worker-sdk==0.5.0"

COPY services/drive-worker/pyproject.toml .
RUN pip install --no-cache-dir -e . 2>/dev/null || \
    pip install --no-cache-dir \
      "boto3>=1.34" "google-api-python-client>=2.100" "google-auth>=2.23" \
      "apscheduler>=3.10,<4" "pydantic-settings>=2.0" "structlog>=23.0" \
      "requests>=2.31" "Pillow>=10.0"

COPY services/drive-worker/src/ src/

RUN useradd -m -u 1000 appuser
USER appuser

CMD ["python", "-m", "src.worker"]
