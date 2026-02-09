# Worker Dockerfile (merged)
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_DEFAULT_TIMEOUT=100

# System deps:
# - ffmpeg: audio/video processing
# - libgomp1: common dependency for numeric/ML libs
# - X/GLib libs: common runtime deps for opencv / image stacks
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    libgomp1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    libxcb1 \
    && rm -rf /var/lib/apt/lists/*

# uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Copy only dependency metadata first for better caching
COPY pyproject.toml ./
# If you have one, include it (recommended). If not, remove this line.
COPY uv.lock ./

# Install deps (prefer locked if uv.lock exists)
# If you have a non-dev extra for the worker, replace with: -e ".[worker]"
RUN uv pip install --system -e .

# Copy source last
COPY src/ ./src/

RUN mkdir -p /app/artifacts

# Replace with your real worker entrypoint
CMD ["python", "--version"]