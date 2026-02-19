#!/usr/bin/env python3
"""Experiment 5: OCR + STT Input Validation

Measures:
- Keyframe extraction from original-res vs 720p proxy
- OCR quality comparison: original keyframes vs proxy keyframes
- Whether 720p proxy degrades OCR accuracy for Korean text
- STT input validation (proxy audio is identical content, just transcoded)

The production pipeline processes original-res keyframes for OCR,
then transcodes to proxy. This experiment validates that approach
by comparing OCR output from both resolutions.

Requires: ffmpeg installed locally, a video file with visible Korean text.
OCR comparison is manual (script extracts keyframes, user inspects).
"""

import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config


KEYFRAME_COUNT = 5


def run() -> dict:
    config.validate()
    config.ensure_dirs()

    results = {
        "experiment": "05_ocr_stt",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "keyframe_extractions": [],
        "errors": [],
    }

    ffmpeg_version = _get_ffmpeg_version()
    if not ffmpeg_version:
        results["errors"].append("ffmpeg not found in PATH")
        print("[05] ✗ ffmpeg not found. Install ffmpeg and retry.")
        _save_results(results)
        return results
    results["ffmpeg_version"] = ffmpeg_version

    service, _, auth_ms = config.get_drive_service()
    session, _, _ = config.get_authorized_session()
    results["auth_ms"] = round(auth_ms, 2)

    test_file = _select_test_file(service)
    if not test_file:
        results["errors"].append("No video file found for OCR testing")
        _save_results(results)
        return results

    print(f"\n[05] Test file: {test_file['name']} ({test_file['size_mb']:.1f} MB)")
    results["test_file"] = test_file

    original_path = config.TEMP_DIR / f"ocr_orig_{test_file['id']}"
    proxy_path = config.TEMP_DIR / f"ocr_proxy_{test_file['id']}.mp4"
    keyframes_orig_dir = config.TEMP_DIR / f"keyframes_orig_{test_file['id']}"
    keyframes_proxy_dir = config.TEMP_DIR / f"keyframes_proxy_{test_file['id']}"

    try:
        # Download original
        print(f"  Downloading original...")
        dl_start = time.monotonic()
        url = f"https://www.googleapis.com/drive/v3/files/{test_file['id']}?alt=media"
        response = session.get(url, stream=True)
        if response.status_code != 200:
            results["errors"].append(f"Download HTTP {response.status_code}")
            _save_results(results)
            return results

        with open(original_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=config.DOWNLOAD_CHUNK_SIZE):
                f.write(chunk)

        dl_ms = (time.monotonic() - dl_start) * 1000
        results["download_ms"] = round(dl_ms, 2)
        print(f"  ✓ Downloaded in {dl_ms / 1000:.1f}s")

        # Probe original
        probe = _ffprobe(original_path)
        if probe:
            results["original_probe"] = probe

        # Extract keyframes from original
        print(f"  Extracting {KEYFRAME_COUNT} keyframes from original...")
        keyframes_orig_dir.mkdir(parents=True, exist_ok=True)
        orig_extraction = _extract_keyframes(original_path, keyframes_orig_dir, "original")
        results["keyframe_extractions"].append(orig_extraction)

        # Transcode to 720p proxy
        print(f"  Transcoding to 720p proxy...")
        tc_start = time.monotonic()
        tc_result = subprocess.run(
            [
                "ffmpeg", "-y", "-i", str(original_path),
                "-vf", "scale=-2:720",
                "-c:v", "libx264", "-crf", "23", "-preset", "medium",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                str(proxy_path),
            ],
            capture_output=True, text=True,
        )
        tc_ms = (time.monotonic() - tc_start) * 1000
        results["transcode_ms"] = round(tc_ms, 2)

        if tc_result.returncode != 0:
            results["errors"].append(f"Transcode failed: exit {tc_result.returncode}")
            print(f"  ✗ Transcode failed")
            _save_results(results)
            return results

        proxy_probe = _ffprobe(proxy_path)
        if proxy_probe:
            results["proxy_probe"] = proxy_probe

        # Extract keyframes from proxy
        print(f"  Extracting {KEYFRAME_COUNT} keyframes from proxy...")
        keyframes_proxy_dir.mkdir(parents=True, exist_ok=True)
        proxy_extraction = _extract_keyframes(proxy_path, keyframes_proxy_dir, "proxy")
        results["keyframe_extractions"].append(proxy_extraction)

        # Resolution comparison
        if probe and proxy_probe:
            results["resolution_comparison"] = {
                "original": f"{probe.get('video_width')}x{probe.get('video_height')}",
                "proxy": f"{proxy_probe.get('video_width')}x{proxy_probe.get('video_height')}",
                "scale_factor": round(
                    probe.get("video_height", 720) / proxy_probe.get("video_height", 720), 2
                ) if proxy_probe.get("video_height") else None,
            }
            print(f"  ✓ Resolution: {results['resolution_comparison']['original']} → "
                  f"{results['resolution_comparison']['proxy']} "
                  f"({results['resolution_comparison']['scale_factor']}x)")

        # Keyframe file size comparison (proxy keyframes should be smaller)
        orig_sizes = _get_keyframe_sizes(keyframes_orig_dir)
        proxy_sizes = _get_keyframe_sizes(keyframes_proxy_dir)

        if orig_sizes and proxy_sizes:
            results["keyframe_size_comparison"] = {
                "original_avg_kb": round(sum(orig_sizes) / len(orig_sizes) / 1024, 1),
                "proxy_avg_kb": round(sum(proxy_sizes) / len(proxy_sizes) / 1024, 1),
                "size_ratio": round(
                    (sum(orig_sizes) / len(orig_sizes)) / (sum(proxy_sizes) / len(proxy_sizes)), 2
                ) if proxy_sizes else None,
            }
            print(f"  ✓ Keyframe sizes: original avg {results['keyframe_size_comparison']['original_avg_kb']:.0f} KB, "
                  f"proxy avg {results['keyframe_size_comparison']['proxy_avg_kb']:.0f} KB")

        # Copy keyframes to logs for manual inspection
        keyframes_output_dir = config.LOG_DIR / "keyframes"
        keyframes_output_dir.mkdir(parents=True, exist_ok=True)

        for src_dir, prefix in [(keyframes_orig_dir, "orig"), (keyframes_proxy_dir, "proxy")]:
            if src_dir.exists():
                for img in sorted(src_dir.glob("*.jpg")):
                    dest = keyframes_output_dir / f"{prefix}_{img.name}"
                    shutil.copy2(img, dest)

        results["keyframes_saved_to"] = str(keyframes_output_dir)
        print(f"  ✓ Keyframes saved to {keyframes_output_dir} for manual OCR comparison")

        results["manual_inspection_note"] = (
            "Compare orig_*.jpg vs proxy_*.jpg in logs/keyframes/. "
            "Run PaddleOCR on both sets to measure character accuracy. "
            "Korean text with small font is the worst case for proxy downscale."
        )

    except Exception as e:
        results["errors"].append(str(e))
        print(f"  ✗ Failed: {e}")

    finally:
        for p in [original_path, proxy_path]:
            if p.exists():
                os.unlink(p)
        for d in [keyframes_orig_dir, keyframes_proxy_dir]:
            if d.exists():
                shutil.rmtree(d, ignore_errors=True)

    _save_results(results)
    return results


def _get_ffmpeg_version() -> str | None:
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, timeout=10,
        )
        return result.stdout.split("\n")[0]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _select_test_file(service) -> dict | None:
    """Pick one video for OCR testing. Prefer a medium-sized MP4."""
    mime_clauses = " or ".join(f"mimeType='{m}'" for m in config.VIDEO_MIME_TYPES)
    query = f"({mime_clauses}) and trashed=false"

    try:
        response = service.files().list(
            corpora="drive",
            driveId=config.DRIVE_ID,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            pageSize=50,
            q=query,
            fields=config.FILE_LIST_FIELDS,
            orderBy="quotaBytesUsed",
        ).execute()
    except Exception as e:
        print(f"  ✗ File listing failed: {e}")
        return None

    files = response.get("files", [])
    # Prefer files between 50-500 MB
    candidates = [
        f for f in files
        if f.get("size") and 50 * 1024 * 1024 <= int(f["size"]) <= 500 * 1024 * 1024
    ]
    if not candidates:
        candidates = [f for f in files if f.get("size")]

    if not candidates:
        return None

    chosen = candidates[0]
    return {
        "id": chosen["id"],
        "name": chosen["name"],
        "mimeType": chosen["mimeType"],
        "size_bytes": int(chosen["size"]),
        "size_mb": round(int(chosen["size"]) / (1024 * 1024), 1),
    }


def _extract_keyframes(video_path: Path, output_dir: Path, label: str) -> dict:
    """Extract N evenly-spaced keyframes from a video."""
    result = {"label": label, "keyframe_count": 0}

    probe = _ffprobe(video_path)
    if not probe or not probe.get("duration_seconds"):
        result["error"] = "Could not determine video duration"
        return result

    duration = probe["duration_seconds"]
    interval = duration / (KEYFRAME_COUNT + 1)

    t0 = time.monotonic()
    extracted = 0

    for i in range(1, KEYFRAME_COUNT + 1):
        timestamp = interval * i
        output_file = output_dir / f"keyframe_{i:03d}.jpg"

        try:
            subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-ss", str(timestamp),
                    "-i", str(video_path),
                    "-frames:v", "1",
                    "-q:v", "2",
                    str(output_file),
                ],
                capture_output=True, text=True, timeout=30,
            )
            if output_file.exists():
                extracted += 1
        except subprocess.TimeoutExpired:
            pass

    extraction_ms = (time.monotonic() - t0) * 1000
    result["keyframe_count"] = extracted
    result["extraction_ms"] = round(extraction_ms, 2)
    result["resolution"] = f"{probe.get('video_width')}x{probe.get('video_height')}"

    print(f"  ✓ {label}: extracted {extracted}/{KEYFRAME_COUNT} keyframes in {extraction_ms / 1000:.1f}s")
    return result


def _get_keyframe_sizes(directory: Path) -> list[int]:
    if not directory.exists():
        return []
    return [f.stat().st_size for f in sorted(directory.glob("*.jpg"))]


def _ffprobe(path: Path) -> dict | None:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", str(path),
            ],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode != 0:
            return None
        data = json.loads(result.stdout)
        fmt = data.get("format", {})
        video_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "video"), {})
        audio_stream = next((s for s in data.get("streams", []) if s.get("codec_type") == "audio"), {})
        return {
            "duration_seconds": float(fmt.get("duration", 0)),
            "format_name": fmt.get("format_name"),
            "video_codec": video_stream.get("codec_name"),
            "video_width": video_stream.get("width"),
            "video_height": video_stream.get("height"),
            "video_bitrate_kbps": round(int(video_stream.get("bit_rate", 0)) / 1000) if video_stream.get("bit_rate") else None,
            "audio_codec": audio_stream.get("codec_name"),
            "audio_sample_rate": audio_stream.get("sample_rate"),
        }
    except Exception:
        return None


def _save_results(results: dict) -> None:
    log_path = config.LOG_DIR / "05_ocr_stt.json"
    with open(log_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[05] Results saved to {log_path}")


if __name__ == "__main__":
    run()
