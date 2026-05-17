#!/usr/bin/env python3
"""Experiment 3: Download Throughput + Resume

Measures:
- Download speed for small (~100 MB), medium (~500 MB), large (1 GB+) files
- Chunked download with manual Range headers (NOT MediaIoBaseDownload)
- Resume after simulated interruption (abort at ~50%, restart from byte offset)
- MD5 verification of completed downloads
- Throughput in MB/s per chunk and overall

Exit criteria validated:
- #5: Chunked download completes for a 1 GB+ video, MD5 matches
- #6: Download resumes after interruption, picks up from byte offset, MD5 matches
"""

import hashlib
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config


# Size buckets for testing
SIZE_BUCKETS = {
    "small": (0, 200 * 1024 * 1024),             # 0-200 MB
    "medium": (200 * 1024 * 1024, 800 * 1024 * 1024),  # 200-800 MB
    "large": (800 * 1024 * 1024, float("inf")),    # 800 MB+
}


def run() -> dict:
    """Run download throughput + resume experiment. Returns results dict."""
    config.validate()
    config.ensure_dirs()

    results = {
        "experiment": "03_download_resume",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "chunk_size_mb": config.DOWNLOAD_CHUNK_SIZE / (1024 * 1024),
        "downloads": [],
        "resume_test": {},
        "errors": [],
    }

    # Get Drive service for file listing
    service, _, auth_ms = config.get_drive_service()
    results["auth_ms"] = round(auth_ms, 2)

    # Get AuthorizedSession for Range header downloads
    session, _, _ = config.get_authorized_session()

    # --- 1. Find test files (one per size bucket) ---
    print("[03] Finding test files by size bucket...")
    test_files = _select_test_files(service, results)

    if not test_files:
        results["errors"].append("No video files found for download testing")
        _save_results(results)
        return results

    # --- 2. Download each test file ---
    for bucket_name, file_info in test_files.items():
        print(f"\n[03] Downloading {bucket_name}: {file_info['name']} "
              f"({file_info['size_mb']:.1f} MB)...")

        download_result = _download_file(session, file_info, results)
        download_result["bucket"] = bucket_name
        results["downloads"].append(download_result)

    # --- 3. Resume test (use medium or largest available file) ---
    resume_file = test_files.get("large") or test_files.get("medium") or test_files.get("small")
    if resume_file:
        print(f"\n[03] Testing download resume on: {resume_file['name']}...")
        results["resume_test"] = _test_resume(session, resume_file, results)

    _save_results(results)
    return results


def _select_test_files(service, results: dict) -> dict:
    """Select one video file per size bucket."""
    mime_clauses = " or ".join(f"mimeType='{m}'" for m in config.VIDEO_MIME_TYPES)
    query = f"({mime_clauses}) and trashed=false"

    try:
        response = service.files().list(
            corpora="drive",
            driveId=config.DRIVE_ID,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            pageSize=1000,
            q=query,
            fields=config.FILE_LIST_FIELDS,
            orderBy="quotaBytesUsed desc",
        ).execute()
    except Exception as e:
        results["errors"].append(f"File listing failed: {e}")
        return {}

    files = response.get("files", [])
    if not files:
        return {}

    # Categorize by size bucket
    selected = {}
    for bucket_name, (min_size, max_size) in SIZE_BUCKETS.items():
        candidates = [
            f for f in files
            if f.get("size") and min_size <= int(f["size"]) < max_size
        ]
        if candidates:
            # Pick the first (largest due to ordering)
            chosen = candidates[0]
            selected[bucket_name] = {
                "id": chosen["id"],
                "name": chosen["name"],
                "mimeType": chosen["mimeType"],
                "size_bytes": int(chosen["size"]),
                "size_mb": round(int(chosen["size"]) / (1024 * 1024), 1),
                "md5Checksum": chosen.get("md5Checksum"),
            }
            print(f"  ✓ {bucket_name}: {chosen['name']} ({selected[bucket_name]['size_mb']:.1f} MB)")
        else:
            print(f"  ⚠ {bucket_name}: no files in this size range")

    return selected


def _download_file(session, file_info: dict, results: dict) -> dict:
    """Download a file using manual Range headers. Returns metrics dict."""
    file_id = file_info["id"]
    file_size = file_info["size_bytes"]
    expected_md5 = file_info.get("md5Checksum")
    download_path = config.TEMP_DIR / f"download_{file_id}"
    chunk_size = config.DOWNLOAD_CHUNK_SIZE

    download_result = {
        "file_id": file_id,
        "name": file_info["name"],
        "size_bytes": file_size,
        "size_mb": file_info["size_mb"],
        "expected_md5": expected_md5,
        "chunk_size_mb": chunk_size / (1024 * 1024),
        "chunks": [],
    }

    url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
    md5_hash = hashlib.md5()
    bytes_downloaded = 0
    chunk_num = 0
    overall_start = time.monotonic()

    try:
        with open(download_path, "wb") as f:
            while bytes_downloaded < file_size:
                range_end = min(bytes_downloaded + chunk_size - 1, file_size - 1)
                headers = {"Range": f"bytes={bytes_downloaded}-{range_end}"}

                chunk_start = time.monotonic()
                response = session.get(url, headers=headers, stream=True)

                if response.status_code not in (200, 206):
                    download_result["error"] = f"HTTP {response.status_code}: {response.text[:200]}"
                    results["errors"].append(f"Download {file_info['name']} chunk {chunk_num}: HTTP {response.status_code}")
                    break

                chunk_bytes = 0
                for data in response.iter_content(chunk_size=8192):
                    f.write(data)
                    md5_hash.update(data)
                    chunk_bytes += len(data)

                chunk_ms = (time.monotonic() - chunk_start) * 1000
                chunk_mbps = (chunk_bytes / (1024 * 1024)) / (chunk_ms / 1000) if chunk_ms > 0 else 0
                bytes_downloaded += chunk_bytes
                chunk_num += 1

                download_result["chunks"].append({
                    "chunk": chunk_num,
                    "bytes": chunk_bytes,
                    "ms": round(chunk_ms, 2),
                    "mbps": round(chunk_mbps, 2),
                })

                progress = (bytes_downloaded / file_size) * 100
                print(f"  [{progress:5.1f}%] Chunk {chunk_num}: {chunk_bytes / (1024 * 1024):.1f} MB "
                      f"in {chunk_ms:.0f} ms ({chunk_mbps:.1f} MB/s)")

        overall_ms = (time.monotonic() - overall_start) * 1000
        overall_mbps = (file_size / (1024 * 1024)) / (overall_ms / 1000) if overall_ms > 0 else 0

        download_result["total_ms"] = round(overall_ms, 2)
        download_result["total_seconds"] = round(overall_ms / 1000, 1)
        download_result["overall_mbps"] = round(overall_mbps, 2)
        download_result["total_chunks"] = chunk_num

        # MD5 verification
        actual_md5 = md5_hash.hexdigest()
        download_result["actual_md5"] = actual_md5
        download_result["md5_match"] = (actual_md5 == expected_md5) if expected_md5 else None

        if expected_md5:
            if actual_md5 == expected_md5:
                print(f"  ✓ MD5 MATCH: {actual_md5}")
            else:
                print(f"  ✗ MD5 MISMATCH: expected={expected_md5}, actual={actual_md5}")
                results["errors"].append(f"MD5 mismatch for {file_info['name']}")
        else:
            print(f"  ⚠ No md5Checksum from Drive to verify against (actual={actual_md5})")

        print(f"  ✓ Complete: {file_info['size_mb']:.1f} MB in {overall_ms / 1000:.1f}s "
              f"({overall_mbps:.1f} MB/s)")

    except Exception as e:
        download_result["error"] = str(e)
        results["errors"].append(f"Download {file_info['name']} failed: {e}")
        print(f"  ✗ Download FAILED: {e}")

    finally:
        # Cleanup downloaded file
        if download_path.exists():
            os.unlink(download_path)

    return download_result


def _test_resume(session, file_info: dict, results: dict) -> dict:
    """Test download resume by aborting at ~50% and restarting."""
    file_id = file_info["id"]
    file_size = file_info["size_bytes"]
    expected_md5 = file_info.get("md5Checksum")
    download_path = config.TEMP_DIR / f"resume_{file_id}"
    chunk_size = config.DOWNLOAD_CHUNK_SIZE

    # Target: download ~50% then "abort"
    abort_at = file_size // 2

    resume_result = {
        "file_id": file_id,
        "name": file_info["name"],
        "size_bytes": file_size,
        "abort_at_bytes": abort_at,
        "abort_at_pct": 50,
    }

    url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
    md5_full = hashlib.md5()

    # --- Phase 1: Download first ~50% ---
    print(f"  [Resume Phase 1] Downloading first 50% ({abort_at / (1024 * 1024):.1f} MB)...")
    bytes_downloaded = 0
    phase1_start = time.monotonic()

    try:
        with open(download_path, "wb") as f:
            while bytes_downloaded < abort_at:
                range_end = min(bytes_downloaded + chunk_size - 1, abort_at - 1)
                headers = {"Range": f"bytes={bytes_downloaded}-{range_end}"}

                response = session.get(url, headers=headers, stream=True)
                if response.status_code not in (200, 206):
                    resume_result["phase1_error"] = f"HTTP {response.status_code}"
                    _save_results(results)
                    return resume_result

                for data in response.iter_content(chunk_size=8192):
                    f.write(data)
                    md5_full.update(data)
                    bytes_downloaded += len(data)

        phase1_ms = (time.monotonic() - phase1_start) * 1000
        resume_result["phase1_ms"] = round(phase1_ms, 2)
        resume_result["phase1_bytes"] = bytes_downloaded
        print(f"  ✓ Phase 1 complete: {bytes_downloaded / (1024 * 1024):.1f} MB in {phase1_ms / 1000:.1f}s")

    except Exception as e:
        resume_result["phase1_error"] = str(e)
        if download_path.exists():
            os.unlink(download_path)
        return resume_result

    # Verify file on disk has correct size
    actual_size_on_disk = download_path.stat().st_size
    resume_result["phase1_size_on_disk"] = actual_size_on_disk
    print(f"  [Resume] File on disk: {actual_size_on_disk / (1024 * 1024):.1f} MB")

    # --- Phase 2: Resume from byte offset ---
    print(f"  [Resume Phase 2] Resuming from byte {actual_size_on_disk}...")
    phase2_start = time.monotonic()
    resume_bytes_downloaded = actual_size_on_disk

    # Re-read the partial file to continue MD5
    # (In production we'd track MD5 state, but for spike just re-hash)
    md5_resume = hashlib.md5()
    with open(download_path, "rb") as f:
        while True:
            data = f.read(8192)
            if not data:
                break
            md5_resume.update(data)

    try:
        with open(download_path, "ab") as f:  # append mode
            while resume_bytes_downloaded < file_size:
                range_end = min(resume_bytes_downloaded + chunk_size - 1, file_size - 1)
                headers = {"Range": f"bytes={resume_bytes_downloaded}-{range_end}"}

                response = session.get(url, headers=headers, stream=True)

                if response.status_code not in (200, 206):
                    resume_result["phase2_error"] = f"HTTP {response.status_code}: {response.text[:200]}"
                    break

                # Check Content-Range header to verify server honored our Range
                content_range = response.headers.get("Content-Range", "")
                if not content_range and resume_bytes_downloaded > 0:
                    resume_result["range_header_honored"] = False
                    print(f"  ⚠ Server did NOT return Content-Range header")
                else:
                    resume_result["range_header_honored"] = True

                chunk_bytes = 0
                for data in response.iter_content(chunk_size=8192):
                    f.write(data)
                    md5_full.update(data)
                    md5_resume.update(data)
                    chunk_bytes += len(data)

                resume_bytes_downloaded += chunk_bytes

        phase2_ms = (time.monotonic() - phase2_start) * 1000
        resume_result["phase2_ms"] = round(phase2_ms, 2)
        resume_result["phase2_bytes"] = resume_bytes_downloaded - actual_size_on_disk
        resume_result["total_bytes_downloaded"] = resume_bytes_downloaded

        # MD5 verification
        actual_md5 = md5_resume.hexdigest()
        resume_result["actual_md5"] = actual_md5
        resume_result["md5_match"] = (actual_md5 == expected_md5) if expected_md5 else None

        if expected_md5:
            if actual_md5 == expected_md5:
                print(f"  ✓ Resume MD5 MATCH: {actual_md5}")
            else:
                print(f"  ✗ Resume MD5 MISMATCH: expected={expected_md5}, actual={actual_md5}")
                results["errors"].append(f"Resume MD5 mismatch for {file_info['name']}")
        else:
            print(f"  ⚠ No md5Checksum to verify (actual={actual_md5})")

        total_ms = resume_result.get("phase1_ms", 0) + phase2_ms
        resume_result["total_ms"] = round(total_ms, 2)
        resume_result["resume_worked"] = resume_result.get("md5_match", resume_bytes_downloaded == file_size)

        print(f"  ✓ Resume complete: total {resume_bytes_downloaded / (1024 * 1024):.1f} MB "
              f"in {total_ms / 1000:.1f}s (resume saved {resume_result.get('phase1_ms', 0) / 1000:.1f}s)")

    except Exception as e:
        resume_result["phase2_error"] = str(e)
        results["errors"].append(f"Resume phase 2 failed: {e}")
        print(f"  ✗ Resume FAILED: {e}")

    finally:
        if download_path.exists():
            os.unlink(download_path)

    return resume_result


def _save_results(results: dict) -> None:
    """Save results to log file."""
    log_path = config.LOG_DIR / "03_download_resume.json"
    with open(log_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[03] Results saved to {log_path}")


if __name__ == "__main__":
    run()
