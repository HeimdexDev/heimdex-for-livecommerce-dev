"""Deterministic export hashing for cache reuse.

Identical basket contents produce the same export hash.
This allows skipping expensive ZIP assembly when the same
scenes have already been exported and the bundle is still in S3.
"""
import hashlib
import json
from typing import Any


def compute_export_hash(
    *,
    org_id: str,
    clips: list[dict[str, Any]],
    include_markers: bool,
    include_transcript_markers: bool,
    clip_gap_ms: int,
) -> str:
    """Compute a deterministic 16-char hex hash for an export request.

    The hash excludes cosmetic options (sequence_name, drive_mount_path)
    that don't affect which proxy files are needed. It includes org_id
    to prevent cross-tenant cache hits.
    """
    normalized = json.dumps(
        {
            "org_id": org_id,
            "clips": sorted(
                [
                    {
                        "scene_id": c["scene_id"],
                        "video_id": c["video_id"],
                        "start_ms": c["start_ms"],
                        "end_ms": c["end_ms"],
                    }
                    for c in clips
                ],
                key=lambda x: x["scene_id"],
            ),
            "markers": include_markers,
            "transcript_markers": include_transcript_markers,
            "gap_ms": clip_gap_ms,
        },
        sort_keys=True,
    )
    return hashlib.sha256(normalized.encode()).hexdigest()[:16]
