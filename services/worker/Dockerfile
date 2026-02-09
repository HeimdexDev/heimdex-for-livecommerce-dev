# Speech Segments Worker Dockerfile
FROM python:3.11-slim

# Install system dependencies (minimal - ffmpeg only)
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Install uv for fast Python dependency management
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Set working directory
WORKDIR /app

# Copy dependency files and source
COPY pyproject.toml ./
COPY src/ ./src/

# Install Python dependencies using uv
# Note: Using --system for container environment (no venv needed)
RUN uv pip install --system -e ".[dev]"

# Create necessary directories
RUN mkdir -p /app/artifacts

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app/src/domain

# Default command
CMD ["python", "--version"]