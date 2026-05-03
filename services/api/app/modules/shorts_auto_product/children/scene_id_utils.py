"""Scene-id parsing helpers for the wizard child runner.

OpenSearch scene_ids in this codebase are ``{video_id}_scene_NNN``
where ``video_id`` is the Drive-style external id (``gd_xxx``) and
``NNN`` is a zero-padded scene index. The runner needs to extract
the ``video_id`` prefix from any appearance's ``scene_id`` to feed
:class:`RenderJobCreate.video_id` (a string of the same shape).

## Why a dedicated helper, not inlined

* Pure-string parsing → unit-testable without any DB or network.
* The format is established convention (CLAUDE.md notes the image
  case at ``drive-worker/src/tasks/process.py:112``); centralizing
  the parser means a future format change has one place to update.
* Decouples the runner from the scene_id format — the runner asks
  for ``os_video_id`` and gets one, no string-fiddling at the
  call site.
"""

from __future__ import annotations

# Sentinel between video id and scene index in the ``{video_id}_scene_NNN``
# scene_id format. Lifted here as a constant so a future format
# change has exactly one place to update.
_SCENE_INFIX = "_scene_"


def os_video_id_from_scene_id(scene_id: str) -> str:
    """Extract the OpenSearch ``video_id`` prefix from a scene_id.

    Examples:
        ``gd_abc123_scene_005`` → ``gd_abc123``
        ``gd_xyz_scene_000``    → ``gd_xyz`` (single-scene image)

    The scene index portion is whatever follows ``_scene_`` — we
    don't validate it; ill-formed indices fall through as part of
    the suffix and get discarded.

    Raises:
        ValueError: scene_id does not contain the ``_scene_``
            sentinel. Indicates either a corrupted DB row or a
            scene_id format change that this helper hasn't caught
            up with.
    """
    if not scene_id:
        raise ValueError("scene_id must be non-empty")
    # ``rsplit`` with maxsplit=1 — there could (in principle) be a
    # video_id containing the literal substring "_scene_"; rsplit
    # picks the LAST occurrence which is the right semantics.
    parts = scene_id.rsplit(_SCENE_INFIX, 1)
    if len(parts) != 2 or not parts[0]:
        raise ValueError(
            f"scene_id {scene_id!r} does not match the "
            f"'{{video_id}}{_SCENE_INFIX}NNN' convention"
        )
    return parts[0]
