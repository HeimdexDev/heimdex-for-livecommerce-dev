"""Port (interface) for highlight reel scene data access.

Defines the protocol that adapters must implement. The domain algorithm
and service layer depend only on this protocol, never on concrete
OpenSearch or database classes.
"""
from __future__ import annotations

from typing import Protocol
from uuid import UUID

from app.modules.highlight_reel.domain import SceneRecord


class SceneDataPort(Protocol):
    """Async interface for fetching scene and exclusion data."""

    async def get_person_scenes(
        self,
        org_id: str,
        person_cluster_id: str,
        limit: int = 1000,
    ) -> list[SceneRecord]:
        """Return all scenes where person_cluster_id appears.

        Scenes must be sorted by (video_id ASC, start_ms ASC) for
        correct run detection in the domain layer.
        """
        ...

    async def get_excluded_video_ids(
        self,
        org_id: UUID,
        user_id: UUID,
        person_cluster_id: str,
    ) -> list[str]:
        """Return video IDs excluded by this user for this person."""
        ...

    async def get_video_titles(
        self,
        org_id: str,
        person_cluster_id: str,
    ) -> dict[str, str | None]:
        """Return {video_id: title} for all videos the person appears in."""
        ...
