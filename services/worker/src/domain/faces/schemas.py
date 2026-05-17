"""Face presence schemas — re-exported from heimdex-media-contracts.

All types are defined in ``heimdex_media_contracts.faces.schemas``.
This module exists solely for backward compatibility with existing imports.
"""

from heimdex_media_contracts.faces.schemas import (  # noqa: F401
    FacePresenceResponse,
    IdentityPresence,
    Interval,
    SceneSummary,
)

__all__ = [
    "Interval",
    "SceneSummary",
    "IdentityPresence",
    "FacePresenceResponse",
]
