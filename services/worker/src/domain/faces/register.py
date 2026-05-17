"""Face identity registration — re-exported from heimdex-media-pipelines.

The registration logic is defined in ``heimdex_media_pipelines.faces.register``.
This module exists solely for backward compatibility with existing imports.
"""

from heimdex_media_pipelines.faces.register import (  # noqa: F401
    build_identity_template,
)

__all__ = [
    "build_identity_template",
]
