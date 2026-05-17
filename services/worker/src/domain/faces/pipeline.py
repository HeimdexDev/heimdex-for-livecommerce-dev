"""Face pipeline — re-exported from heimdex-media-pipelines.

The pipeline logic is defined in ``heimdex_media_pipelines.faces.pipeline``.
This module exists solely for backward compatibility with existing imports.
"""

from heimdex_media_pipelines.faces.pipeline import (  # noqa: F401
    run_pipeline,
)

__all__ = [
    "run_pipeline",
]
