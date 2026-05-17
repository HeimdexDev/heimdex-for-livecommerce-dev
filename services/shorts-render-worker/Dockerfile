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
RUN pip install --no-cache-dir "heimdex-worker-sdk==0.5.1"

# Install Python dependencies.
# heimdex-media-contracts + heimdex-media-pipelines are volume-mounted
# in local dev (docker-compose) and pip-installed --no-deps at startup.
# Pillow is bundled here because pipelines' [composition] extra defines
# it but `pip install --no-deps` doesn't honor extras — so the bake_overlay_png
# render path would crash with ModuleNotFoundError without this line.
RUN pip install --no-cache-dir \
      "boto3>=1.34" "pydantic-settings>=2.0" \
      "structlog>=23.0" "requests>=2.31" "pydantic>=2.0" \
      "Pillow>=10.0"

# Bundle Korean fonts. We ship Pretendard + NotoSansKR Regular + Bold.
# Italic variants for Korean fonts don't exist (Pretendard has weight
# variants only; NotoSansKR italic is Latin-only). The bake_overlay_png
# function in heimdex_media_pipelines.composition.overlay_render falls
# back to faux-italic via PIL transform skew when ov.italic=True and no
# *-Italic.ttf is found in font_dir — see _resolve_italic_font_path.
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
