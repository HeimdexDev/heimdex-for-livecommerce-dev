FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
# Install PyPI-available deps only; internal packages (heimdex-media-contracts,
# heimdex-media-pipelines) are mounted and installed at container startup via
# the docker-compose command override.
RUN pip install --no-cache-dir -e . 2>/dev/null || \
    pip install --no-cache-dir \
      "sqlalchemy[asyncio]>=2.0" "asyncpg>=0.29" "psycopg2-binary>=2.9" \
      "boto3>=1.34" "google-api-python-client>=2.100" "google-auth>=2.23" \
      "apscheduler>=3.10,<4" "pydantic-settings>=2.0" "structlog>=23.0" \
      "requests>=2.31"

COPY src/ src/

RUN useradd -m -u 1000 appuser
USER appuser

CMD ["python", "-m", "src.worker"]
