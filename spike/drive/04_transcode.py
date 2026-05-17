#!/usr/bin/env python3
"""Experiment 4: Transcode Performance

Measures:
- 720p proxy generation time via ffmpeg
- CPU and RAM usage during transcode
- Output file size vs original (compression ratio)
- Quality settings: H.264 CRF 23, AAC 128k
- Tests multiple input sizes

Proxy spec from ARCHITECTURE.md:
  Video: H.264, 720p, CRF 23, preset medium
  Audio: AAC 128k
  Container: MP4 (faststart)

Requires: ffmpeg installed locally, experiment 03 must have identified test files.
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


FFMPEG_PROXY_ARGS = [
    "-vf", "scale=-2:720",
    "-c:v", "libx264",
    "-crf", "23",
    "-preset", "medium",
    "-c:a", "aac",
    "-b:a", "128k",
    "-movflags", "+faststart",
]


def run() -> dict:
    config.validate()
    config.ensure_dirs()

    results = {
        "experiment": "04_transcode",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "ffmpeg_version": _get_ffmpeg_version(),
        "transcodes": [],
        "errors": [],
    }

    if not results["ffmpeg_version"]:
        results["errors"].append("ffmpeg not found in PATH")
        print("[04] ✗ ffmpeg not found. Install ffmpeg and retry.")
        _save_results(results)
        return results

    service, _, auth_ms = config.get_drive_service()
    session, _, _ = config.get_authorized_session()
    results["auth_ms"] = round(auth_ms, 2)

    test_files = _select_transcode_files(service)
    if not test_files:
        results["errors"].append("No video files found for transcode testing")
        _save_results(results)
        return results

    for label, file_info in test_files.items():
        print(f"\n[04] Transcoding {label}: {file_info['name']} ({file_info['size_mb']:.1f} MB)...")
        transcode_result = _download_and_transcode(session, file_info, label)
        results["transcodes"].append(transcode_result)

        if transcode_result.get("error"):
            results["errors"].append(f"{label}: {transcode_result['error']}")

    _save_results(results)
    return results


def _get_ffmpeg_version() -> str | None:
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True, timeout=10,
        )
        first_line = result.stdout.split("\n")[0]
        return first_line
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def _select_transcode_files(service) -> dict:
    """Pick 1-2 files for transcode testing (prefer small + medium to save time)."""
    mime_clauses = " or ".join(f"mimeType='{m}'" for m in config.VIDEO_MIME_TYPES)
    query = f"({mime_clauses}) and trashed=false"

    try:
        response = service.files().list(
            corpora="drive",
            driveId=config.DRIVE_ID,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            pageSize=100,
            q=query,
            fields=config.FILE_LIST_FIELDS,
            orderBy="quotaBytesUsed",
        ).execute()
    except Exception as e:
        print(f"  ✗ File listing failed: {e}")
        return {}

    files = response.get("files", [])
    selected = {}

    # Pick smallest file for quick test
    small_files = [f for f in files if f.get("size") and int(f["size"]) < 200 * 1024 * 1024]
    if small_files:
        f = small_files[0]
        selected["small"] = {
            "id": f["id"],
            "name": f["name"],
            "mimeType": f["mimeType"],
            "size_bytes": int(f["size"]),
            "size_mb": round(int(f["size"]) / (1024 * 1024), 1),
        }

    # Pick a medium file (200-800 MB) if available
    medium_files = [
        f for f in files
        if f.get("size") and 200 * 1024 * 1024 <= int(f["size"]) < 800 * 1024 * 1024
    ]
    if medium_files:
        f = medium_files[0]
        selected["medium"] = {
            "id": f["id"],
            "name": f["name"],
            "mimeType": f["mimeType"],
            "size_bytes": int(f["size"]),
            "size_mb": round(int(f["size"]) / (1024 * 1024), 1),
        }

    for label, info in selected.items():
        print(f"  ✓ {label}: {info['name']} ({info['size_mb']:.1f} MB)")

    return selected


def _download_and_transcode(session, file_info: dict, label: str) -> dict:
    """Download a file then transcode to 720p proxy. Measures both phases."""
    file_id = file_info["id"]
    original_path = config.TEMP_DIR / f"transcode_orig_{file_id}"
    proxy_path = config.TEMP_DIR / f"transcode_proxy_{file_id}.mp4"

    result = {
        "label": label,
        "file_id": file_id,
        "name": file_info["name"],
        "original_size_bytes": file_info["size_bytes"],
        "original_size_mb": file_info["size_mb"],
    }

    try:
        # Download
        print(f"  Downloading original...")
        dl_start = time.monotonic()
        url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
        response = session.get(url, stream=True)
        if response.status_code != 200:
            result["error"] = f"Download HTTP {response.status_code}"
            return result

        with open(original_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=config.DOWNLOAD_CHUNK_SIZE):
                f.write(chunk)

        dl_ms = (time.monotonic() - dl_start) * 1000
        result["download_ms"] = round(dl_ms, 2)
        result["download_seconds"] = round(dl_ms / 1000, 1)
        print(f"  ✓ Downloaded in {dl_ms / 1000:.1f}s")

        # Probe original
        probe = _ffprobe(original_path)
        if probe:
            result["original_probe"] = probe

        # Transcode
        print(f"  Transcoding to 720p proxy...")
        tc_start = time.monotonic()

        try:
            import psutil
            process = subprocess.Popen(
                [
                    "ffmpeg", "-y", "-i", str(original_path),
                    *FFMPEG_PROXY_ARGS,
                    str(proxy_path),
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            cpu_samples = []
            mem_samples = []
            ps_proc = psutil.Process(process.pid)

            while process.poll() is None:
                try:
                    cpu_samples.append(ps_proc.cpu_percent(interval=1.0))
                    mem_samples.append(ps_proc.memory_info().rss / (1024 * 1024))
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    break

            stdout, stderr = process.communicate()
        except ImportError:
            # psutil not available, run without monitoring
            proc_result = subprocess.run(
                [
                    "ffmpeg", "-y", "-i", str(original_path),
                    *FFMPEG_PROXY_ARGS,
                    str(proxy_path),
                ],
                capture_output=True, text=True,
            )
            process = proc_result
            cpu_samples = []
            mem_samples = []

        tc_ms = (time.monotonic() - tc_start) * 1000
        result["transcode_ms"] = round(tc_ms, 2)
        result["transcode_seconds"] = round(tc_ms / 1000, 1)

        exit_code = process.returncode if hasattr(process, "returncode") else process.returncode
        result["ffmpeg_exit_code"] = exit_code

        if exit_code != 0:
            stderr_text = stderr.decode() if isinstance(stderr, bytes) else (getattr(process, "stderr", "") or "")
            result["error"] = f"ffmpeg exit code {exit_code}"
            result["ffmpeg_stderr_tail"] = str(stderr_text)[-500:]
            print(f"  ✗ ffmpeg failed (exit {exit_code})")
            return result

        # Proxy file metrics
        if proxy_path.exists():
            proxy_size = proxy_path.stat().st_size
            result["proxy_size_bytes"] = proxy_size
            result["proxy_size_mb"] = round(proxy_size / (1024 * 1024), 1)
            result["compression_ratio"] = round(file_info["size_bytes"] / proxy_size, 2) if proxy_size > 0 else None
            result["size_reduction_pct"] = round((1 - proxy_size / file_info["size_bytes"]) * 100, 1) if file_info["size_bytes"] > 0 else None

            proxy_probe = _ffprobe(proxy_path)
            if proxy_probe:
                result["proxy_probe"] = proxy_probe

            print(f"  ✓ Proxy: {result['proxy_size_mb']:.1f} MB "
                  f"({result['compression_ratio']:.1f}x compression, "
                  f"{result['size_reduction_pct']:.0f}% reduction)")

        if cpu_samples:
            result["cpu_avg_pct"] = round(sum(cpu_samples) / len(cpu_samples), 1)
            result["cpu_max_pct"] = round(max(cpu_samples), 1)
        if mem_samples:
            result["mem_avg_mb"] = round(sum(mem_samples) / len(mem_samples), 1)
            result["mem_max_mb"] = round(max(mem_samples), 1)

        # Speed ratio: original duration / transcode wall time
        if probe and probe.get("duration_seconds") and tc_ms > 0:
            speed_ratio = probe["duration_seconds"] / (tc_ms / 1000)
            result["speed_ratio"] = round(speed_ratio, 2)
            print(f"  ✓ Transcode speed: {speed_ratio:.1f}x realtime ({tc_ms / 1000:.1f}s)")

        print(f"  ✓ Transcode complete in {tc_ms / 1000:.1f}s")

    except Exception as e:
        result["error"] = str(e)
        print(f"  ✗ Failed: {e}")

    finally:
        if original_path.exists():
            os.unlink(original_path)
        if proxy_path.exists():
            os.unlink(proxy_path)

    return result


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
    log_path = config.LOG_DIR / "04_transcode.json"
    with open(log_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[04] Results saved to {log_path}")


if __name__ == "__main__":
    run()
