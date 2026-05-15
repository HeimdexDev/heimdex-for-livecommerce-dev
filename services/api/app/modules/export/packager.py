"""Premiere Pro export package assembler.

Builds a ZIP archive containing:
- {sequence_name}.fcpxml  — the FCPXML 1.8 timeline
- manifest.json           — canonical mapping with export metadata
- README.txt              — import instructions (Korean + English)
- scenes.csv              — spreadsheet for editors

The packager is a pure function: given FCPXML content and clip metadata,
it produces a ZIP archive as bytes. No database access, no I/O beyond
in-memory ZIP creation.
"""

import csv
import io
import json
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from uuid import uuid4


@dataclass(frozen=True)
class ExportClipMetadata:
    """Metadata for a single clip in the export package.

    Used to populate manifest.json and scenes.csv — NOT for FCPXML generation
    (that's handled by fcpxml_writer.py separately).
    """

    scene_id: str
    video_id: str
    video_title: str
    source_file: str  # filename only, e.g. "라이브커머스 세일.mp4"
    source_path: str  # relative path within Google Drive
    google_drive_link: str  # web_view_link for fallback
    edit_in_ms: int
    edit_out_ms: int
    fps: float
    width: int
    height: int
    keyword_tags: list[str] = field(default_factory=list)
    transcript_raw: str = ""
    label: Optional[str] = None


@dataclass(frozen=True)
class PackageOptions:
    """Configuration for the export package."""

    sequence_name: str = "Heimdex Export"
    drive_mount_path: str = ""
    clip_gap_ms: int = 0
    include_markers: bool = True
    include_transcript_markers: bool = False


def package_premiere_export(
    fcpxml_content: str,
    clips: list[ExportClipMetadata],
    options: PackageOptions,
) -> bytes:
    """Create a ZIP archive with FCPXML + manifest + README + CSV.

    Returns the ZIP as raw bytes suitable for HTTP response.
    """
    export_id = str(uuid4())
    now = datetime.now(timezone.utc)

    manifest = _build_manifest(export_id, now, clips, options)
    readme = _build_readme(now, clips, options)
    csv_content = _build_scenes_csv(clips)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{_safe_filename(options.sequence_name)}.fcpxml", fcpxml_content)
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.writestr("README.txt", readme)
        zf.writestr("scenes.csv", csv_content)

    return buf.getvalue()


def _safe_filename(name: str, max_len: int = 100) -> str:
    """Sanitize a string for use as a filename."""
    import re
    import unicodedata

    cleaned = "".join(
        c for c in name if not unicodedata.category(c).startswith("C")
    )
    cleaned = re.sub(r"[^\w\s\-_.,()]", "_", cleaned)
    cleaned = cleaned.strip()
    if len(cleaned) > max_len:
        cleaned = cleaned[:max_len]
    return cleaned or "heimdex_export"


def _build_manifest(
    export_id: str,
    export_date: datetime,
    clips: list[ExportClipMetadata],
    options: PackageOptions,
) -> dict[str, object]:
    """Build the manifest.json structure."""
    total_duration_ms = sum(c.edit_out_ms - c.edit_in_ms for c in clips)
    return {
        "export_id": export_id,
        "export_date": export_date.isoformat(),
        "sequence_name": options.sequence_name,
        "drive_mount_path": options.drive_mount_path,
        "heimdex_version": "1.0",
        "total_clips": len(clips),
        "total_duration_ms": total_duration_ms,
        "options": {
            "clip_gap_ms": options.clip_gap_ms,
            "include_markers": options.include_markers,
            "include_transcript_markers": options.include_transcript_markers,
        },
        "items": [
            {
                "scene_id": c.scene_id,
                "video_id": c.video_id,
                "video_title": c.video_title,
                "source_file": c.source_file,
                "source_path": c.source_path,
                "google_drive_link": c.google_drive_link,
                "edit_in_ms": c.edit_in_ms,
                "edit_out_ms": c.edit_out_ms,
                "fps": c.fps,
                "width": c.width,
                "height": c.height,
            }
            for c in clips
        ],
    }


def _ms_to_timecode(ms: int, fps: float = 29.97) -> str:
    """Convert milliseconds to HH:MM:SS:FF timecode string."""
    if fps <= 0:
        fps = 29.97
    total_frames = round(ms * fps / 1000)
    frames = total_frames % round(fps)
    total_seconds = total_frames // round(fps)
    seconds = total_seconds % 60
    minutes = (total_seconds // 60) % 60
    hours = total_seconds // 3600
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}:{frames:02d}"


def _build_readme(
    export_date: datetime,
    clips: list[ExportClipMetadata],
    options: PackageOptions,
) -> str:
    """Build the README.txt with Korean + English instructions."""
    # Collect unique source videos
    seen_videos: dict[str, ExportClipMetadata] = {}
    for c in clips:
        if c.video_id not in seen_videos:
            seen_videos[c.video_id] = c

    date_str = export_date.strftime("%Y-%m-%d %H:%M UTC")

    video_list_lines: list[str] = []
    drive_link_lines: list[str] = []
    for clip in seen_videos.values():
        video_list_lines.append(f"  - {clip.video_title}")
        if clip.source_path:
            video_list_lines.append(f"    경로: {clip.source_path}")
        if clip.google_drive_link:
            video_list_lines.append(f"    Google Drive: {clip.google_drive_link}")
            drive_link_lines.append(f"  {clip.video_title}: {clip.google_drive_link}")

    video_list = "\n".join(video_list_lines) if video_list_lines else "  (없음)"
    drive_links = "\n".join(drive_link_lines) if drive_link_lines else "  (없음)"

    return f"""\
=== Heimdex Premiere Pro 내보내기 패키지 ===
=== Heimdex Premiere Pro Export Package ===

시퀀스: {options.sequence_name}
내보내기 날짜: {date_str}
클립 수: {len(clips)}

--- Premiere Pro에서 가져오기 ---

1. 이 ZIP 파일을 폴더에 압축 해제합니다
2. Premiere Pro를 엽니다 (2024 이상 권장)
3. 파일 > 가져오기 (Ctrl+I / Cmd+I)
4. .fcpxml 파일을 선택합니다
5. Premiere가 새 시퀀스를 자동으로 생성합니다

--- 미디어 연결 (중요) ---

이 내보내기는 Google 드라이브의 원본 미디어 파일을 참조합니다.
Google 드라이브 데스크톱 앱이 실행 중이고 파일이 동기화되어 있어야 합니다.

내보내기에 사용된 Google 드라이브 경로:
  {options.drive_mount_path}

미디어가 오프라인으로 표시되는 경우:
1. Premiere에서 오프라인 클립을 마우스 오른쪽 버튼으로 클릭
2. "미디어 연결..." 선택
3. Google 드라이브 마운트 위치로 이동:
   - macOS (최신): ~/Library/CloudStorage/GoogleDrive-이메일@gmail.com/
   - macOS (레거시): /Volumes/GoogleDrive/
   - Windows: G:\\ (드라이브 문자는 다를 수 있음)
4. 원본 파일을 찾아 연결합니다

--- 소스 비디오 ---
{video_list}

--- Google 드라이브에서 직접 열기 ---
아래 링크를 클릭하면 브라우저에서 원본 파일을 확인할 수 있습니다:
{drive_links}

--- Generated by Heimdex ---
"""


def _build_scenes_csv(clips: list[ExportClipMetadata]) -> str:
    """Build scenes.csv as a UTF-8 string with BOM for Excel compatibility."""
    buf = io.StringIO()
    # UTF-8 BOM for Excel to recognize encoding
    _ = buf.write("\ufeff")

    writer = csv.writer(buf)
    writer.writerow([
        "scene_id",
        "video_title",
        "source_file",
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
            c.source_file,
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
