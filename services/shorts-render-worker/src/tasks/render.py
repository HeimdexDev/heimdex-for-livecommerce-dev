import logging

from src.message_adapter import RenderJobMessage

logger = logging.getLogger(__name__)


def process_render_job(*, api_client, settings, render_job: RenderJobMessage) -> None:
    """Process a shorts render job.

    Placeholder — full implementation in Task 09 (ffmpeg composition engine).
    """
    logger.info(
        "render_job_received",
        extra={
            "job_id": render_job.job_id,
            "org_id": render_job.org_id,
        },
    )
    raise NotImplementedError("Render composition not yet implemented (Task 09)")
