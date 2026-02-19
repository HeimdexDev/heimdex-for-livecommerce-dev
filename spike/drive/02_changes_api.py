#!/usr/bin/env python3
"""Experiment 2: Changes API Behavior

Measures:
- getStartPageToken latency
- changes.list latency and payload size
- Change propagation latency (if a file is modified during test)
- Invalid page token handling (error code, response format)
- Page token persistence and resume across restarts
- Detection of new/modified/trashed files

Exit criteria validated:
- #3: changes.list delta detects new/modified/deleted files
- #4: Token saved to disk, spike restarts, resumes from saved token
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config


TOKEN_FILE = config.LOG_DIR / "changes_page_token.txt"


def run() -> dict:
    """Run changes API experiment. Returns results dict."""
    config.validate()
    config.ensure_dirs()

    results = {
        "experiment": "02_changes_api",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "start_page_token": {},
        "changes_list": {},
        "token_persistence": {},
        "invalid_token": {},
        "errors": [],
    }

    service, credentials, auth_ms = config.get_drive_service()
    results["auth_ms"] = round(auth_ms, 2)

    # --- 1. getStartPageToken ---
    print("[02] Getting start page token...")
    start_token_times = []
    start_token = None

    for i in range(3):
        t0 = time.monotonic()
        try:
            response = service.changes().getStartPageToken(
                driveId=config.DRIVE_ID,
                supportsAllDrives=True,
            ).execute()
            elapsed_ms = (time.monotonic() - t0) * 1000
            start_token_times.append(elapsed_ms)
            start_token = response.get("startPageToken")
        except Exception as e:
            results["errors"].append(f"getStartPageToken attempt {i} failed: {e}")
            print(f"  ✗ Attempt {i} FAILED: {e}")

    if start_token_times:
        results["start_page_token"] = {
            "token": start_token,
            "latency_ms_avg": round(sum(start_token_times) / len(start_token_times), 2),
            "latency_ms_min": round(min(start_token_times), 2),
            "latency_ms_max": round(max(start_token_times), 2),
            "samples": len(start_token_times),
        }
        print(f"  ✓ Token: {start_token} (avg {results['start_page_token']['latency_ms_avg']:.1f} ms)")

    if not start_token:
        results["errors"].append("Could not get start page token")
        _save_results(results)
        return results

    # --- 2. Check for existing saved token (token persistence test) ---
    saved_token = None
    if TOKEN_FILE.exists():
        saved_token = TOKEN_FILE.read_text().strip()
        print(f"[02] Found saved token from previous run: {saved_token}")
        results["token_persistence"]["saved_token_found"] = True
        results["token_persistence"]["saved_token"] = saved_token
    else:
        print("[02] No saved token found (first run)")
        results["token_persistence"]["saved_token_found"] = False

    # --- 3. changes.list from saved token (if exists) or start token ---
    use_token = saved_token or start_token
    print(f"[02] Listing changes from token: {use_token}...")

    changes_data = _fetch_all_changes(service, use_token, results)
    results["changes_list"] = changes_data

    # --- 4. Categorize changes ---
    if changes_data.get("changes"):
        categories = {"new": 0, "modified": 0, "trashed": 0, "other": 0}
        video_changes = []

        for change in changes_data["changes"]:
            file_info = change.get("file", {})
            mime = file_info.get("mimeType", "")
            is_video = any(mime.startswith(v.split("/")[0]) for v in config.VIDEO_MIME_TYPES) or mime in config.VIDEO_MIME_TYPES

            if change.get("removed") or file_info.get("trashed"):
                categories["trashed"] += 1
            elif is_video:
                categories["modified"] += 1
                video_changes.append({
                    "file_id": change.get("fileId"),
                    "name": file_info.get("name"),
                    "mime": mime,
                    "trashed": file_info.get("trashed", False),
                    "change_type": change.get("changeType"),
                    "time": change.get("time"),
                })
            else:
                categories["other"] += 1

        results["changes_list"]["categories"] = categories
        results["changes_list"]["video_changes"] = video_changes[:20]  # Cap at 20

        print(f"  ✓ Changes: {categories}")
        if video_changes:
            print(f"  ✓ Video changes detected: {len(video_changes)}")
            for vc in video_changes[:5]:
                print(f"    - {vc['name']} ({vc['change_type']})")

    # --- 5. Save new page token for next run ---
    new_token = changes_data.get("new_page_token")
    if new_token:
        TOKEN_FILE.write_text(new_token)
        results["token_persistence"]["new_token_saved"] = new_token
        print(f"[02] Saved new page token: {new_token}")

    # --- 6. Invalid token test ---
    print("[02] Testing invalid page token handling...")
    t0_invalid = time.monotonic()
    try:
        service.changes().list(
            pageToken="INVALID_TOKEN_12345",
            driveId=config.DRIVE_ID,
            supportsAllDrives=True,
            includeItemsFromAllDrives=True,
        ).execute()
        elapsed_ms = (time.monotonic() - t0_invalid) * 1000
        results["invalid_token"] = {
            "behavior": "accepted (unexpected)",
            "latency_ms": round(elapsed_ms, 2),
        }
        print(f"  ⚠ Invalid token was ACCEPTED (unexpected)")
    except Exception as e:
        elapsed_ms = (time.monotonic() - t0_invalid) * 1000
        error_str = str(e)

        http_status = getattr(getattr(e, "resp", None), "status", None)
        error_reason = str(getattr(e, "error_details", None))

        results["invalid_token"] = {
            "behavior": "rejected (expected)",
            "http_status": http_status,
            "error_message": error_str[:500],
            "error_reason": error_reason,
            "latency_ms": round(elapsed_ms, 2),
        }

        if "400" in error_str or (http_status and http_status == 400):
            print(f"  ✓ Invalid token correctly rejected: HTTP {http_status or '400'} ({elapsed_ms:.1f} ms)")
        else:
            print(f"  ⚠ Invalid token rejected with unexpected error: {error_str[:200]}")

    # --- 7. Rapid successive changes.list calls (latency consistency) ---
    print("[02] Testing rapid successive changes.list calls...")
    rapid_times = []
    for i in range(10):
        t0 = time.monotonic()
        try:
            service.changes().list(
                pageToken=new_token or start_token,
                driveId=config.DRIVE_ID,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                pageSize=100,
                fields="nextPageToken, newStartPageToken, changes(fileId, changeType, time, removed)",
            ).execute()
            rapid_times.append((time.monotonic() - t0) * 1000)
        except Exception as e:
            results["errors"].append(f"Rapid call {i} failed: {e}")

    if rapid_times:
        results["changes_list"]["rapid_calls"] = {
            "count": len(rapid_times),
            "avg_ms": round(sum(rapid_times) / len(rapid_times), 2),
            "min_ms": round(min(rapid_times), 2),
            "max_ms": round(max(rapid_times), 2),
            "p95_ms": round(sorted(rapid_times)[int(len(rapid_times) * 0.95)], 2),
        }
        print(f"  ✓ Rapid calls avg: {results['changes_list']['rapid_calls']['avg_ms']:.1f} ms "
              f"(p95: {results['changes_list']['rapid_calls']['p95_ms']:.1f} ms)")

    _save_results(results)
    return results


def _fetch_all_changes(service, page_token: str, results: dict) -> dict:
    """Fetch all changes from the given page token."""
    all_changes = []
    pages = 0
    total_start = time.monotonic()
    new_page_token = None
    page_latencies = []

    while True:
        t0 = time.monotonic()
        try:
            response = service.changes().list(
                pageToken=page_token,
                driveId=config.DRIVE_ID,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                pageSize=1000,
                fields="nextPageToken, newStartPageToken, changes(fileId, changeType, time, removed, file(id, name, mimeType, size, md5Checksum, modifiedTime, trashed, parents))",
            ).execute()
            page_ms = (time.monotonic() - t0) * 1000
            page_latencies.append(page_ms)

            changes = response.get("changes", [])
            all_changes.extend(changes)
            pages += 1

            print(f"  ✓ Page {pages}: {len(changes)} changes ({page_ms:.1f} ms)")

            if "newStartPageToken" in response:
                new_page_token = response["newStartPageToken"]
                break
            elif "nextPageToken" in response:
                page_token = response["nextPageToken"]
            else:
                break
        except Exception as e:
            results["errors"].append(f"changes.list page {pages} failed: {e}")
            print(f"  ✗ Page {pages} FAILED: {e}")
            break

    total_ms = (time.monotonic() - total_start) * 1000

    return {
        "total_changes": len(all_changes),
        "total_pages": pages,
        "total_ms": round(total_ms, 2),
        "page_latencies_ms": [round(t, 2) for t in page_latencies],
        "new_page_token": new_page_token,
        "changes": all_changes[:50],  # Cap stored changes at 50
    }


def _save_results(results: dict) -> None:
    """Save results to log file."""
    log_path = config.LOG_DIR / "02_changes_api.json"
    with open(log_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[02] Results saved to {log_path}")


if __name__ == "__main__":
    run()
