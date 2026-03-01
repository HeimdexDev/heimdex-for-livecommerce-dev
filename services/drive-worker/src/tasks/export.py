"""Proxy-pack export task for the drive-worker.

Downloads proxies from S3, generates FCPXML with relative paths,
assembles a ZIP bundle, uploads to S3, and updates the export record
via internal HTTP API. No direct database access.
"""
# pyright: reportMissingImports=false

import csv
import hashlib
import io
import json
import logging
import re
import shutil
import tempfile
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote
from xml.etree import ElementTree as ET

from heimdex_worker_sdk.internal_api import InternalAPIClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ClipInput:
    scene_id: str
    video_id: str
    video_title: str
    start_ms: int
    end_ms: int
    label: str
    keyword_tags: list[str]
    transcript_raw: str


def handle_export_proxy_pack(
    message: dict[str, Any],
    api_client: InternalAPIClient,
    settings: Any,
) -> None:
    export_id = message.get("export_id", "")
    if not export_id:
        logger.error("export_missing_export_id", extra={"message": message})
        return

    record = _fetch_export_record(api_client, export_id)
    if record is None:
        return

    if record["status"] != "pending":
        logger.info(
            "export_already_processed",
            extra={"export_id": export_id, "status": record["status"]},
        )
        return

    _update_status(api_client, export_id, "generating")

    tmp_dir = Path(tempfile.mkdtemp(prefix="heimdex_export_"))
    try:
        request_body = record["request_body"]
        org_id = record["org_id"]

        clips = _parse_clips(request_body.get("clips", []))
        if not clips:
            _update_status(api_client, export_id, "failed", error_message="No clips in request")
            return

        deduped_video_ids = list({c.video_id for c in clips})
        proxy_keys = request_body.get("proxy_keys", {})
        proxy_map = _download_proxies(
            tmp_dir=tmp_dir,
            video_ids=deduped_video_ids,
            org_id=org_id,
            settings=settings,
            proxy_keys=proxy_keys,
        )

        if not proxy_map:
            _update_status(api_client, export_id, "failed", error_message="No proxies found in S3")
            return

        sequence_name = request_body.get("sequence_name", "Heimdex Export")
        include_markers = request_body.get("include_markers", True)
        include_transcript_markers = request_body.get("include_transcript_markers", False)
        clip_gap_ms = request_body.get("clip_gap_ms", 0)

        fcpxml_content = _generate_fcpxml_relative(
            clips=clips,
            proxy_map=proxy_map,
            sequence_name=sequence_name,
            include_markers=include_markers,
            include_transcript_markers=include_transcript_markers,
            clip_gap_ms=clip_gap_ms,
        )

        _update_status(api_client, export_id, "uploading")

        zip_path = tmp_dir / "export.zip"
        _assemble_zip(
            zip_path=zip_path,
            fcpxml_content=fcpxml_content,
            clips=clips,
            proxy_map=proxy_map,
            sequence_name=sequence_name,
            export_id=export_id,
            expires_at=record.get("expires_at", ""),
        )

        zip_size = zip_path.stat().st_size
        export_hash = record["export_hash"]
        s3_key = f"exports/{org_id}/{export_hash}.zip"

        _upload_to_s3(zip_path, s3_key, settings)

        _update_status(
            api_client, export_id, "ready",
            s3_key=s3_key,
            size_bytes=zip_size,
        )

        logger.info(
            "export_completed",
            extra={
                "export_id": export_id,
                "s3_key": s3_key,
                "zip_size_bytes": zip_size,
                "proxy_count": len(proxy_map),
                "clip_count": len(clips),
            },
        )

    except Exception as e:
        logger.exception("export_failed", extra={"export_id": export_id})
        _update_status(api_client, export_id, "failed", error_message=str(e)[:500])
        raise
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _fetch_export_record(
    api_client: InternalAPIClient,
    export_id: str,
) -> dict[str, Any] | None:
    try:
        resp = api_client._session.get(
            f"{api_client.base_url}/internal/export/{export_id}",
            timeout=30,
        )
        if resp.status_code == 404:
            logger.warning("export_record_not_found", extra={"export_id": export_id})
            return None
        resp.raise_for_status()
        return resp.json()
    except Exception:
        logger.exception("export_fetch_failed", extra={"export_id": export_id})
        return None


def _update_status(
    api_client: InternalAPIClient,
    export_id: str,
    status: str,
    *,
    s3_key: str | None = None,
    size_bytes: int | None = None,
    error_message: str | None = None,
) -> None:
    body: dict[str, Any] = {"status": status}
    if s3_key is not None:
        body["s3_key"] = s3_key
    if size_bytes is not None:
        body["size_bytes"] = size_bytes
    if error_message is not None:
        body["error_message"] = error_message
    try:
        resp = api_client._session.patch(
            f"{api_client.base_url}/internal/export/{export_id}/status",
            json=body,
            timeout=30,
        )
        resp.raise_for_status()
    except Exception:
        logger.exception(
            "export_status_update_failed",
            extra={"export_id": export_id, "status": status},
        )


def _parse_clips(raw_clips: list[dict[str, Any]]) -> list[_ClipInput]:
    result: list[_ClipInput] = []
    for c in raw_clips:
        result.append(_ClipInput(
            scene_id=c.get("scene_id", ""),
            video_id=c.get("video_id", ""),
            video_title=c.get("video_title", ""),
            start_ms=c.get("start_ms", 0),
            end_ms=c.get("end_ms", 0),
            label=c.get("label", "") or "",
            keyword_tags=c.get("keyword_tags", []),
            transcript_raw=c.get("transcript_raw", ""),
        ))
    return result


def _download_proxies(
    *,
    tmp_dir: Path,
    video_ids: list[str],
    org_id: str,
    settings: Any,
    proxy_keys: dict[str, str] | None = None,
) -> dict[str, Path]:
    """Download deduplicated proxy files from S3. Returns {video_id: local_path}.

    Uses pre-resolved proxy_keys from the export record when available.
    Falls back to S3 listing search (legacy, unreliable for gd_ video IDs).
    """
    import boto3
    from botocore.config import Config as BotoConfig

    _MINIO_DISABLED = {"", "none", "disabled"}
    endpoint = getattr(settings, "minio_endpoint", "")
    use_real_s3 = endpoint.strip().lower() in _MINIO_DISABLED

    if use_real_s3:
        s3 = boto3.client(
            "s3",
            config=BotoConfig(retries={"max_attempts": 3, "mode": "adaptive"}),
            region_name=settings.s3_region,
        )
    else:
        s3 = boto3.client(
            "s3",
            endpoint_url=f"{'https' if settings.minio_secure else 'http'}://{endpoint}",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            config=BotoConfig(
                retries={"max_attempts": 3, "mode": "adaptive"},
                s3={"addressing_style": "path"},
            ),
            region_name="us-east-1",
        )

    bucket = settings.drive_s3_bucket
    media_dir = tmp_dir / "media"
    media_dir.mkdir(exist_ok=True)

    proxy_map: dict[str, Path] = {}
    for video_id in video_ids:
        # Use pre-resolved key from API (reliable), fall back to S3 search (legacy)
        proxy_key = (proxy_keys or {}).get(video_id) or _find_proxy_key(s3, bucket, org_id, video_id)
        if proxy_key is None:
            logger.warning("export_proxy_not_found", extra={"video_id": video_id, "had_proxy_key": video_id in (proxy_keys or {})})
            continue

        filename = f"proxy_{video_id}.mp4"
        local_path = media_dir / filename
        logger.info("export_downloading_proxy", extra={"video_id": video_id, "s3_key": proxy_key})
        s3.download_file(bucket, proxy_key, str(local_path))
        proxy_map[video_id] = local_path

    return proxy_map


def _find_proxy_key(s3: Any, bucket: str, org_id: str, video_id: str) -> str | None:
    """Find the proxy S3 key for a video. Searches the known key pattern."""
    prefix = f"{org_id}/drive/"
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj["Key"]
            if key.endswith("/proxy.mp4") and video_id in key:
                return key
    return None


# ── Minimal FCPXML generator (worker-side, no app.* imports) ──────────

_STANDARD_FPS = (23.976, 24.0, 25.0, 29.97, 30.0, 50.0, 59.94, 60.0)
_FPS_RATIONAL = {
    23.976: (1001, 24000), 24.0: (100, 2400), 25.0: (100, 2500),
    29.97: (1001, 30000), 30.0: (100, 3000), 50.0: (100, 5000),
    59.94: (1001, 60000), 60.0: (100, 6000),
}


def _snap_fps(value: float) -> float:
    if value <= 0:
        return 29.97
    return min(_STANDARD_FPS, key=lambda s: abs(s - value))


def _ms_to_rational(ms: int, fps: float) -> str:
    snapped = _snap_fps(fps)
    fd, tb = _FPS_RATIONAL[snapped]
    frames = round(ms * tb / (1000 * fd))
    if frames < 0:
        frames = 0
    return f"{frames * fd}/{tb}s"


def _ms_to_rational_min1(ms: int, fps: float) -> str:
    snapped = _snap_fps(fps)
    fd, tb = _FPS_RATIONAL[snapped]
    frames = max(1, round(ms * tb / (1000 * fd)))
    return f"{frames * fd}/{tb}s"


def _generate_fcpxml_relative(
    *,
    clips: list[_ClipInput],
    proxy_map: dict[str, Path],
    sequence_name: str,
    include_markers: bool,
    include_transcript_markers: bool,
    clip_gap_ms: int,
) -> str:
    fps = 29.97
    width, height = 1280, 720

    fcpxml = ET.Element("fcpxml", {"version": "1.8"})
    resources = ET.SubElement(fcpxml, "resources")

    snapped = _snap_fps(fps)
    fd, tb = _FPS_RATIONAL[snapped]
    fmt_id = "r1"
    ET.SubElement(resources, "format", {
        "id": fmt_id,
        "frameDuration": f"{fd}/{tb}s",
        "width": str(width),
        "height": str(height),
        "colorSpace": "1-1-1 (Rec. 709)",
    })

    resource_index = 2
    asset_by_video: dict[str, str] = {}

    for clip in clips:
        vid = clip.video_id
        if vid in asset_by_video:
            continue
        if vid not in proxy_map:
            continue

        asset_id = f"r{resource_index}"
        resource_index += 1
        asset_by_video[vid] = asset_id

        relative_path = f"media/proxy_{vid}.mp4"
        encoded_src = "/".join(quote(p, safe="") for p in relative_path.split("/"))
        uid = hashlib.md5(relative_path.encode()).hexdigest().upper()

        clip_dur = max(1, clip.end_ms - clip.start_ms)
        asset = ET.SubElement(resources, "asset", {
            "id": asset_id,
            "uid": uid,
            "src": encoded_src,
            "start": "0s",
            "duration": _ms_to_rational_min1(clip_dur, fps),
            "hasVideo": "1",
            "hasAudio": "1",
            "format": fmt_id,
            "audioSources": "1",
            "audioChannels": "2",
            "audioRate": "48000",
        })
        ET.SubElement(asset, "media-rep", {"kind": "original-media", "src": encoded_src})

    library = ET.SubElement(fcpxml, "library")
    event = ET.SubElement(library, "event", {"name": "Heimdex Export"})
    project = ET.SubElement(event, "project", {"name": sequence_name[:512]})

    sequence = ET.SubElement(project, "sequence", {
        "format": fmt_id,
        "duration": "0s",
        "tcStart": "0s",
        "tcFormat": "NDF",
        "audioLayout": "stereo",
        "audioRate": "48k",
    })
    spine = ET.SubElement(sequence, "spine")

    timeline_ms = 0
    for i, clip in enumerate(clips):
        vid = clip.video_id
        if vid not in asset_by_video:
            continue

        clip_dur = max(1, clip.end_ms - clip.start_ms)
        clip_node = ET.SubElement(spine, "asset-clip", {
            "ref": asset_by_video[vid],
            "offset": _ms_to_rational(timeline_ms, fps),
            "name": (clip.label or clip.video_title or clip.scene_id)[:1024],
            "duration": _ms_to_rational_min1(clip_dur, fps),
            "start": _ms_to_rational(clip.start_ms, fps),
            "audioRole": "dialogue",
        })

        if include_markers and (clip.label or clip.keyword_tags):
            note_parts: list[str] = []
            if clip.label:
                note_parts.append(clip.label)
            if clip.keyword_tags:
                note_parts.append("Tags: " + ", ".join(clip.keyword_tags))
            ET.SubElement(clip_node, "marker", {
                "start": _ms_to_rational(clip.start_ms, fps),
                "duration": _ms_to_rational_min1(clip_dur, fps),
                "value": "standard",
                "note": " | ".join(note_parts)[:4096],
            })

        if include_transcript_markers and clip.transcript_raw:
            ET.SubElement(clip_node, "marker", {
                "start": _ms_to_rational(clip.start_ms, fps),
                "duration": _ms_to_rational_min1(clip_dur, fps),
                "value": "standard",
                "note": clip.transcript_raw[:200],
            })

        timeline_ms += clip_dur
        if clip_gap_ms > 0 and i < len(clips) - 1:
            ET.SubElement(spine, "gap", {
                "offset": _ms_to_rational(timeline_ms, fps),
                "duration": _ms_to_rational_min1(clip_gap_ms, fps),
            })
            timeline_ms += clip_gap_ms

    sequence.set("duration", _ms_to_rational_min1(timeline_ms, fps))

    xml_body = ET.tostring(fcpxml, encoding="unicode")
    return '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + xml_body + "\n"


# ── ZIP assembly ──────────────────────────────────────────────────────

def _safe_filename(name: str, max_len: int = 100) -> str:
    cleaned = "".join(c for c in name if not unicodedata.category(c).startswith("C"))
    cleaned = re.sub(r"[^\w\s\-_.,()]", "_", cleaned)
    cleaned = cleaned.strip()
    return cleaned[:max_len] if len(cleaned) > max_len else (cleaned or "heimdex_export")


def _assemble_zip(
    *,
    zip_path: Path,
    fcpxml_content: str,
    clips: list[_ClipInput],
    proxy_map: dict[str, Path],
    sequence_name: str,
    export_id: str,
    expires_at: str,
) -> None:
    safe_name = _safe_filename(sequence_name)

    manifest = {
        "export_id": export_id,
        "export_type": "proxy-pack",
        "sequence_name": sequence_name,
        "heimdex_version": "1.1",
        "total_clips": len(clips),
        "total_proxies": len(proxy_map),
        "expires_at": expires_at,
    }

    readme = _build_readme(sequence_name, len(proxy_map))
    csv_content = _build_csv(clips)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr(f"{safe_name}.fcpxml", fcpxml_content)
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr("README.txt", readme)
        zf.writestr("scenes.csv", csv_content)

        for vid, local_path in proxy_map.items():
            zf.write(local_path, f"media/proxy_{vid}.mp4")


def _build_readme(sequence_name: str, proxy_count: int) -> str:
    return f"""\
=== Heimdex Premiere Pro Export (Proxy Pack) ===

Sequence: {sequence_name}
Proxies: {proxy_count}

--- How to use ---

1. Extract this ZIP to a folder
2. Open Premiere Pro (2024 or later)
3. File > Import (Ctrl+I / Cmd+I)
4. Select the .fcpxml file
5. Premiere will find media in the media/ folder automatically

IMPORTANT: The media/ folder and .fcpxml must be in the same folder!

--- Relinking to originals ---

These are 720p proxy files. For final output, relink to originals:
1. Select media in the Project panel
2. Right-click > Link Media...
3. Navigate to your original files

--- Generated by Heimdex ---
"""


def _build_csv(clips: list[_ClipInput]) -> str:
    buf = io.StringIO()
    buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow(["scene_id", "video_id", "video_title", "start_ms", "end_ms", "duration_ms", "tags", "transcript"])
    for c in clips:
        writer.writerow([
            c.scene_id,
            c.video_id,
            c.video_title,
            c.start_ms,
            c.end_ms,
            c.end_ms - c.start_ms,
            ", ".join(c.keyword_tags),
            c.transcript_raw[:500] if c.transcript_raw else "",
        ])
    return buf.getvalue()


def _upload_to_s3(zip_path: Path, s3_key: str, settings: Any) -> None:
    import boto3
    from botocore.config import Config as BotoConfig

    _MINIO_DISABLED = {"", "none", "disabled"}
    endpoint = getattr(settings, "minio_endpoint", "")
    use_real_s3 = endpoint.strip().lower() in _MINIO_DISABLED

    if use_real_s3:
        s3 = boto3.client(
            "s3",
            config=BotoConfig(retries={"max_attempts": 3, "mode": "adaptive"}),
            region_name=settings.s3_region,
        )
    else:
        s3 = boto3.client(
            "s3",
            endpoint_url=f"{'https' if settings.minio_secure else 'http'}://{endpoint}",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            config=BotoConfig(
                retries={"max_attempts": 3, "mode": "adaptive"},
                s3={"addressing_style": "path"},
            ),
            region_name="us-east-1",
        )

    s3.upload_file(
        str(zip_path),
        settings.drive_s3_bucket,
        s3_key,
        ExtraArgs={"ContentType": "application/zip"},
    )
    logger.info("export_uploaded_to_s3", extra={"s3_key": s3_key, "size": zip_path.stat().st_size})
