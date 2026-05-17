"""Face detection frame sampling — re-exported from heimdex-media-pipelines.

The sampling logic (cv2 video probe + pure math) is defined in
``heimdex_media_pipelines.faces.sampling``.  Pure math is further delegated
to ``heimdex_media_contracts.faces.sampling``.

This module exists solely for backward compatibility with existing imports.
"""

from heimdex_media_pipelines.faces.sampling import (  # noqa: F401
    sample_timestamps,
)

# Also re-export the pure math helper for anyone who imported it directly
from heimdex_media_contracts.faces.sampling import (  # noqa: F401
    _dedupe_sorted,
    sample_timestamps as _sample_timestamps_pure,
)

__all__ = [
    "sample_timestamps",
]
