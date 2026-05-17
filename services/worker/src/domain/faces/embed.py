"""Face embedding — re-exported from heimdex-media-pipelines.

The embedding logic is defined in ``heimdex_media_pipelines.faces.embed``.
This module exists solely for backward compatibility with existing imports.
"""

from heimdex_media_pipelines.faces.embed import (  # noqa: F401
    extract_embeddings,
    run_embeddings,
)

__all__ = [
    "extract_embeddings",
    "run_embeddings",
]
