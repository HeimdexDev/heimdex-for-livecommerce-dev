FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
RUN sed -i '/"heimdex-media-contracts"/d' pyproject.toml && \
    pip install --no-cache-dir -e ".[dev]"

COPY . .

ARG PRELOAD_EMBEDDING_MODEL=false
ENV HF_HOME=/home/appuser/.cache/huggingface

RUN if [ "$PRELOAD_EMBEDDING_MODEL" = "true" ]; then \
    python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('intfloat/multilingual-e5-large')"; \
    fi

RUN useradd -m -u 1000 appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*", "--reload"]
