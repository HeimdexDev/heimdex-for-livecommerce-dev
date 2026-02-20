FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY pyproject.toml .
RUN pip install --no-cache-dir -e . 2>/dev/null || \
    pip install --no-cache-dir \
      "sqlalchemy[asyncio]>=2.0" "asyncpg>=0.29" "psycopg2-binary>=2.9" \
      "boto3>=1.34" "apscheduler>=3.10,<4" "pydantic-settings>=2.0" \
      "structlog>=23.0" "requests>=2.31" \
      "transformers==4.44.2" "torch>=2.0" "torchvision>=0.15" "Pillow>=9.0" \
      "einops>=0.7" "timm>=0.9"

COPY src/ src/

RUN useradd -m -u 1000 appuser
USER appuser

CMD ["python", "-m", "src.worker"]
