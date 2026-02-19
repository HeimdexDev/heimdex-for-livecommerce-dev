#!/usr/bin/env python3
"""Experiment 1: Auth + List Performance

Measures:
- DWD authentication time (cold start)
- DWD authentication time (warm / token reuse)
- files.list latency for a Shared Drive (pageSize variations)
- Number of video files found and metadata completeness
- Quota usage per operation (from response headers)

Exit criteria validated:
- #1: DWD auth succeeds against a real Shared Drive
- #2: files.list returns video files with required metadata fields
- #8: DWD propagation timing documented (first auth latency)
"""

import json
import sys
import time
from pathlib import Path

# Add parent to path for config import
sys.path.insert(0, str(Path(__file__).parent))
import config


def run() -> dict:
    """Run auth + list experiment. Returns results dict."""
    config.validate()
    config.ensure_dirs()

    results = {
        "experiment": "01_auth_list",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "auth": {},
        "listing": {},
        "files_found": [],
        "errors": [],
    }

    # --- 1. Cold auth ---
    print("[01] Testing cold DWD authentication...")
    try:
        service, credentials, cold_auth_ms = config.get_drive_service()
        results["auth"]["cold_auth_ms"] = round(cold_auth_ms, 2)
        print(f"  ✓ Cold auth: {cold_auth_ms:.1f} ms")
    except Exception as e:
        results["auth"]["cold_auth_ms"] = None
        results["auth"]["cold_auth_error"] = str(e)
        results["errors"].append(f"Cold auth failed: {e}")
        print(f"  ✗ Cold auth FAILED: {e}")
        _save_results(results)
        return results

    # --- 2. Warm auth (reuse credentials object) ---
    print("[01] Testing warm auth (token reuse)...")
    warm_times = []
    for i in range(5):
        t0 = time.monotonic()
        # Force token refresh by making a lightweight API call
        try:
            service.about().get(fields="user").execute()
            warm_ms = (time.monotonic() - t0) * 1000
            warm_times.append(warm_ms)
        except Exception as e:
            results["errors"].append(f"Warm auth attempt {i} failed: {e}")

    if warm_times:
        results["auth"]["warm_auth_ms_avg"] = round(sum(warm_times) / len(warm_times), 2)
        results["auth"]["warm_auth_ms_min"] = round(min(warm_times), 2)
        results["auth"]["warm_auth_ms_max"] = round(max(warm_times), 2)
        results["auth"]["warm_auth_samples"] = len(warm_times)
        print(f"  ✓ Warm auth avg: {results['auth']['warm_auth_ms_avg']:.1f} ms "
              f"(min={results['auth']['warm_auth_ms_min']:.1f}, max={results['auth']['warm_auth_ms_max']:.1f})")

    # --- 3. files.list with different page sizes ---
    print("[01] Testing files.list latencies...")
    page_sizes = [10, 50, 100, 500, 1000]
    listing_results = []

    # Build query for video files only
    mime_clauses = " or ".join(f"mimeType='{m}'" for m in config.VIDEO_MIME_TYPES)
    query = f"({mime_clauses}) and trashed=false"

    for ps in page_sizes:
        t0 = time.monotonic()
        try:
            response = service.files().list(
                corpora="drive",
                driveId=config.DRIVE_ID,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                pageSize=ps,
                q=query,
                fields=config.FILE_LIST_FIELDS,
            ).execute()
            elapsed_ms = (time.monotonic() - t0) * 1000
            file_count = len(response.get("files", []))
            has_next = "nextPageToken" in response

            listing_results.append({
                "page_size": ps,
                "latency_ms": round(elapsed_ms, 2),
                "files_returned": file_count,
                "has_next_page": has_next,
            })
            print(f"  ✓ pageSize={ps}: {elapsed_ms:.1f} ms, {file_count} files, next_page={has_next}")
        except Exception as e:
            listing_results.append({
                "page_size": ps,
                "latency_ms": None,
                "error": str(e),
            })
            results["errors"].append(f"files.list pageSize={ps} failed: {e}")
            print(f"  ✗ pageSize={ps} FAILED: {e}")

    results["listing"]["page_size_tests"] = listing_results

    # --- 4. Full paginated listing (count all videos) ---
    print("[01] Full paginated listing of all video files...")
    all_files = []
    page_token = None
    total_pages = 0
    full_list_start = time.monotonic()

    while True:
        try:
            kwargs = {
                "corpora": "drive",
                "driveId": config.DRIVE_ID,
                "includeItemsFromAllDrives": True,
                "supportsAllDrives": True,
                "pageSize": 1000,
                "q": query,
                "fields": config.FILE_LIST_FIELDS,
            }
            if page_token:
                kwargs["pageToken"] = page_token

            response = service.files().list(**kwargs).execute()
            files = response.get("files", [])
            all_files.extend(files)
            total_pages += 1
            page_token = response.get("nextPageToken")

            if not page_token:
                break
        except Exception as e:
            results["errors"].append(f"Full listing page {total_pages} failed: {e}")
            print(f"  ✗ Page {total_pages} FAILED: {e}")
            break

    full_list_ms = (time.monotonic() - full_list_start) * 1000
    results["listing"]["full_list_ms"] = round(full_list_ms, 2)
    results["listing"]["total_video_files"] = len(all_files)
    results["listing"]["total_pages"] = total_pages
    print(f"  ✓ Found {len(all_files)} video files in {total_pages} pages ({full_list_ms:.1f} ms)")

    # --- 5. Check metadata completeness ---
    print("[01] Checking metadata completeness...")
    required_fields = ["id", "name", "mimeType", "size", "md5Checksum", "modifiedTime"]
    files_summary = []

    for f in all_files:
        file_info = {
            "id": f.get("id"),
            "name": f.get("name"),
            "mimeType": f.get("mimeType"),
            "size_bytes": int(f["size"]) if f.get("size") else None,
            "size_mb": round(int(f["size"]) / (1024 * 1024), 1) if f.get("size") else None,
            "md5Checksum": f.get("md5Checksum"),
            "modifiedTime": f.get("modifiedTime"),
            "missing_fields": [k for k in required_fields if k not in f],
        }
        files_summary.append(file_info)

    results["files_found"] = files_summary

    # Size distribution
    sizes = [f["size_bytes"] for f in files_summary if f["size_bytes"]]
    if sizes:
        results["listing"]["size_distribution"] = {
            "min_mb": round(min(sizes) / (1024 * 1024), 1),
            "max_mb": round(max(sizes) / (1024 * 1024), 1),
            "avg_mb": round(sum(sizes) / len(sizes) / (1024 * 1024), 1),
            "total_gb": round(sum(sizes) / (1024 ** 3), 2),
        }
        print(f"  ✓ Size range: {results['listing']['size_distribution']['min_mb']} MB "
              f"- {results['listing']['size_distribution']['max_mb']} MB "
              f"(total: {results['listing']['size_distribution']['total_gb']} GB)")

    # Files missing fields
    missing = [f for f in files_summary if f["missing_fields"]]
    if missing:
        results["listing"]["files_missing_fields"] = len(missing)
        print(f"  ⚠ {len(missing)} files missing required fields")
        for f in missing[:3]:
            print(f"    - {f['name']}: missing {f['missing_fields']}")

    # --- 6. Quota check via about() ---
    print("[01] Checking quota info...")
    try:
        t0 = time.monotonic()
        about = service.about().get(fields="storageQuota, user").execute()
        about_ms = (time.monotonic() - t0) * 1000
        results["auth"]["about_latency_ms"] = round(about_ms, 2)
        results["auth"]["user_email"] = about.get("user", {}).get("emailAddress")
        print(f"  ✓ Authenticated as: {results['auth']['user_email']} ({about_ms:.1f} ms)")
    except Exception as e:
        results["errors"].append(f"about() failed: {e}")
        print(f"  ✗ about() FAILED: {e}")

    _save_results(results)
    return results


def _save_results(results: dict) -> None:
    """Save results to log file."""
    log_path = config.LOG_DIR / "01_auth_list.json"
    with open(log_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[01] Results saved to {log_path}")


if __name__ == "__main__":
    run()
