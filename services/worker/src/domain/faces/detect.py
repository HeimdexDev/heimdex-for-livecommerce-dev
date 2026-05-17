"""Face detection — re-exported from heimdex-media-pipelines.

The detection logic is defined in ``heimdex_media_pipelines.faces.detect``.
This module exists solely for backward compatibility with existing imports.
"""

from heimdex_media_pipelines.faces.detect import (  # noqa: F401
    detect_faces,
)

__all__ = [
    "detect_faces",
]
