"""Pre-flight size estimation and limit checking for proxy-pack exports.

Validates export feasibility BEFORE enqueuing the SQS job,
preventing waste of worker resources on exports that will fail.
"""
from dataclasses import dataclass
from typing import Any

from app.modules.drive.models import DriveFile


@dataclass(frozen=True)
class ExportSizeEstimate:
    """Result of a pre-flight size estimation."""

    proxy_bytes: int
    metadata_bytes: int
    zip_overhead_bytes: int
    total_bytes: int
    proxy_count: int
    clip_count: int


def estimate_export_size(
    *,
    deduplicated_files: dict[str, DriveFile],
    clip_count: int,
) -> ExportSizeEstimate:
    """Estimate total ZIP size from deduplicated proxy sizes.

    ZIP_STORED adds ~0.1% overhead (ZIP headers, central directory).
    Metadata files (FCPXML + manifest + README + CSV) are ~50KB.
    """
    proxy_bytes = sum(
        df.proxy_size_bytes or 0
        for df in deduplicated_files.values()
        if df.proxy_s3_key
    )
    metadata_bytes = 50_000  # ~50KB for FCPXML + manifest + README + CSV
    zip_overhead = int(proxy_bytes * 0.001)  # ZIP headers: ~0.1%
    total = proxy_bytes + metadata_bytes + zip_overhead

    return ExportSizeEstimate(
        proxy_bytes=proxy_bytes,
        metadata_bytes=metadata_bytes,
        zip_overhead_bytes=zip_overhead,
        total_bytes=total,
        proxy_count=len(deduplicated_files),
        clip_count=clip_count,
    )


def deduplicate_proxies(
    clips: list[dict[str, Any]],
    drive_files: dict[str, DriveFile],
) -> dict[str, DriveFile]:
    """Return unique {video_id: DriveFile} map for proxy downloads.

    Multiple scenes may reference the same source video.
    We download each proxy exactly once.
    """
    seen: dict[str, DriveFile] = {}
    for clip in clips:
        video_id = clip["video_id"]
        if video_id not in seen and video_id in drive_files:
            seen[video_id] = drive_files[video_id]
    return seen
