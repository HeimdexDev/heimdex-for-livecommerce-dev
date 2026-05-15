"""Disk-based ZIP assembler for proxy-pack exports.

Unlike packager.py (in-memory, for FCPXML-only exports), this module
writes directly to disk using ZIP_STORED — required because proxy
media files can total 50MB–2GB.
"""
import csv
import io
import json
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .packager import ExportClipMetadata, _ms_to_timecode


@dataclass(frozen=True)
class ProxyPackOptions:
    sequence_name: str = "Heimdex Export"
    clip_gap_ms: int = 0
    include_markers: bool = True
    include_transcript_markers: bool = False
    export_id: str = ""
    expires_at: str = ""


@dataclass(frozen=True)
class ProxyFileInfo:
    video_id: str
    video_title: str
    original_filename: str
    google_drive_link: str
    proxy_size_bytes: int
    duration_ms: int
    fps: float
    width: int
    height: int
    local_path: Path
    zip_filename: str


def _safe_filename(name: str, max_len: int = 100) -> str:
    cleaned = "".join(
        c for c in name if not unicodedata.category(c).startswith("C")
    )
    cleaned = re.sub(r"[^\w\s\-_.,()]", "_", cleaned)
    cleaned = cleaned.strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len]
    return cleaned or "heimdex_export"


def build_proxy_pack_zip(
    *,
    zip_path: Path,
    fcpxml_content: str,
    clips: list[ExportClipMetadata],
    proxy_files: list[ProxyFileInfo],
    options: ProxyPackOptions,
) -> int:
    """Assemble a proxy-pack ZIP on disk. Returns final ZIP size in bytes."""
    safe_name = _safe_filename(options.sequence_name)
    manifest = _build_proxy_manifest(options, clips, proxy_files)
    readme = _build_proxy_readme(options, proxy_files)
    csv_content = _build_proxy_csv(clips)

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_STORED) as zf:
        zf.writestr(f"{safe_name}.fcpxml", fcpxml_content)
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr("README.txt", readme)
        zf.writestr("scenes.csv", csv_content)

        for pf in proxy_files:
            zf.write(pf.local_path, f"media/{pf.zip_filename}")

    return zip_path.stat().st_size


def _build_proxy_manifest(
    options: ProxyPackOptions,
    clips: list[ExportClipMetadata],
    proxy_files: list[ProxyFileInfo],
) -> dict[str, Any]:
    total_duration_ms = sum(c.edit_out_ms - c.edit_in_ms for c in clips)
    total_size = sum(pf.proxy_size_bytes for pf in proxy_files)

    return {
        "export_id": options.export_id or str(uuid4()),
        "export_date": datetime.now(timezone.utc).isoformat(),
        "export_type": "proxy-pack",
        "sequence_name": options.sequence_name,
        "heimdex_version": "1.1",
        "proxy_quality": {
            "max_height": 720,
            "codec": "H.264",
            "container": "MP4",
            "note": "These are proxy-quality files for draft editing. Relink to originals for final output.",
        },
        "total_clips": len(clips),
        "total_proxies": len(proxy_files),
        "total_duration_ms": total_duration_ms,
        "total_size_bytes": total_size,
        "media_files": [
            {
                "filename": pf.zip_filename,
                "video_id": pf.video_id,
                "video_title": pf.video_title,
                "original_filename": pf.original_filename,
                "google_drive_link": pf.google_drive_link,
                "proxy_size_bytes": pf.proxy_size_bytes,
                "duration_ms": pf.duration_ms,
                "fps": pf.fps,
                "width": pf.width,
                "height": pf.height,
            }
            for pf in proxy_files
        ],
        "clips": [
            {
                "scene_id": c.scene_id,
                "video_id": c.video_id,
                "proxy_file": f"proxy_{c.video_id}.mp4",
                "start_ms": c.edit_in_ms,
                "end_ms": c.edit_out_ms,
                "tags": c.keyword_tags,
                "transcript": (c.transcript_raw[:200] if c.transcript_raw else ""),
            }
            for c in clips
        ],
        "expires_at": options.expires_at,
    }


def _build_proxy_readme(
    options: ProxyPackOptions,
    proxy_files: list[ProxyFileInfo],
) -> str:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    proxy_list_lines: list[str] = []
    for pf in proxy_files:
        proxy_list_lines.append(f"  - {pf.video_title} ({pf.zip_filename})")
        if pf.google_drive_link:
            proxy_list_lines.append(f"    원본: {pf.google_drive_link}")

    proxy_list = "\n".join(proxy_list_lines) if proxy_list_lines else "  (없음)"

    return f"""\
=== Heimdex Premiere Pro 내보내기 패키지 (프록시 팩) ===
=== Heimdex Premiere Pro Export Package (Proxy Pack) ===

시퀀스: {options.sequence_name}
내보내기 날짜: {date_str}
프록시 수: {len(proxy_files)}

이 패키지에는 편집용 프록시 미디어가 포함되어 있습니다.
Google 드라이브 데스크톱 앱이 필요하지 않습니다.

This package includes proxy media for draft editing.
No Google Drive desktop app required.

--- 사용 방법 ---

1. ZIP 파일을 폴더에 압축 해제합니다
2. Premiere Pro를 엽니다 (2024 이상)
3. 파일 > 가져오기 (Ctrl+I / Cmd+I)
4. .fcpxml 파일을 선택합니다
5. Premiere가 자동으로 media/ 폴더에서 프록시를 찾습니다

중요: media/ 폴더와 .fcpxml 파일은 같은 폴더에 있어야 합니다!

--- 원본 미디어로 교체하기 ---

이 파일들은 720p 프록시입니다. 최종 출력에는 원본이 필요합니다.

1. 프로젝트 패널에서 미디어를 선택합니다
2. 마우스 오른쪽 버튼 > 미디어 연결...
3. 원본 파일이 있는 위치로 이동합니다

--- 포함된 프록시 ---
{proxy_list}

--- Generated by Heimdex ---
"""


def _build_proxy_csv(clips: list[ExportClipMetadata]) -> str:
    buf = io.StringIO()
    _ = buf.write("\ufeff")
    writer = csv.writer(buf)
    writer.writerow([
        "scene_id",
        "video_title",
        "proxy_file",
        "start_timecode",
        "end_timecode",
        "duration_ms",
        "fps",
        "width",
        "height",
        "tags",
        "transcript",
        "google_drive_link",
    ])
    for c in clips:
        writer.writerow([
            c.scene_id,
            c.video_title,
            f"proxy_{c.video_id}.mp4",
            _ms_to_timecode(c.edit_in_ms, c.fps),
            _ms_to_timecode(c.edit_out_ms, c.fps),
            c.edit_out_ms - c.edit_in_ms,
            c.fps,
            c.width,
            c.height,
            ", ".join(c.keyword_tags),
            c.transcript_raw[:500] if c.transcript_raw else "",
            c.google_drive_link,
        ])
    return buf.getvalue()
