#!/usr/bin/env python3
"""Experiment 6: Quota & Rate Limit Stress Test

Measures:
- Parallel download throughput (concurrent Range-header downloads)
- Rapid files.list calls until 429 (or quota cap)
- First 429 occurrence (request count)
- Exponential backoff effectiveness
- Per-user vs per-project quota behavior

Drive API quotas (documented):
  - 12,000 queries per 60 seconds per project
  - Per-user limit: ~12 queries/second (burst)
  - DWD: quota charged to impersonated user

Exit criteria validated:
- #7: Force rate limit → script backs off and retries → succeeds
"""

import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import config


def run() -> dict:
    config.validate()
    config.ensure_dirs()

    results = {
        "experiment": "06_quota_stress",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "rapid_listing": {},
        "parallel_downloads": {},
        "backoff_test": {},
        "errors": [],
    }

    service, _, auth_ms = config.get_drive_service()
    results["auth_ms"] = round(auth_ms, 2)

    # --- 1. Rapid files.list stress test ---
    print("[06] Rapid files.list stress test...")
    results["rapid_listing"] = _rapid_listing_test(service)

    # --- 2. Parallel download stress test ---
    print("\n[06] Parallel download stress test...")
    session, _, _ = config.get_authorized_session()
    results["parallel_downloads"] = _parallel_download_test(service, session)

    # --- 3. Backoff effectiveness test ---
    print("\n[06] Exponential backoff test...")
    results["backoff_test"] = _backoff_test(service)

    _save_results(results)
    return results


def _rapid_listing_test(service) -> dict:
    """Fire files.list as fast as possible until 429 or 200 requests."""
    max_requests = 200
    latencies = []
    first_429_at = None
    errors = []

    mime_clauses = " or ".join(f"mimeType='{m}'" for m in config.VIDEO_MIME_TYPES)
    query = f"({mime_clauses}) and trashed=false"

    for i in range(max_requests):
        t0 = time.monotonic()
        try:
            service.files().list(
                corpora="drive",
                driveId=config.DRIVE_ID,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                pageSize=10,
                q=query,
                fields="files(id)",
            ).execute()
            elapsed_ms = (time.monotonic() - t0) * 1000
            latencies.append(elapsed_ms)
        except Exception as e:
            elapsed_ms = (time.monotonic() - t0) * 1000
            error_str = str(e)

            if "429" in error_str or "rateLimitExceeded" in error_str or "userRateLimitExceeded" in error_str:
                if first_429_at is None:
                    first_429_at = i + 1
                    print(f"  ✓ First 429 at request #{i + 1} ({elapsed_ms:.1f} ms)")
                errors.append({"request": i + 1, "type": "429", "ms": round(elapsed_ms, 2)})
            else:
                errors.append({"request": i + 1, "type": "other", "error": error_str[:200], "ms": round(elapsed_ms, 2)})

            if first_429_at and (i + 1 - first_429_at) >= 10:
                print(f"  Stopping after 10 consecutive 429s")
                break

    result = {
        "total_requests": len(latencies) + len(errors),
        "successful_requests": len(latencies),
        "first_429_at_request": first_429_at,
        "errors": errors[:20],
    }

    if latencies:
        result["latency_avg_ms"] = round(sum(latencies) / len(latencies), 2)
        result["latency_min_ms"] = round(min(latencies), 2)
        result["latency_max_ms"] = round(max(latencies), 2)
        result["latency_p95_ms"] = round(sorted(latencies)[int(len(latencies) * 0.95)], 2)
        result["requests_per_second"] = round(
            len(latencies) / (sum(latencies) / 1000), 2
        ) if sum(latencies) > 0 else 0

        print(f"  ✓ {len(latencies)}/{max_requests} succeeded, "
              f"avg {result['latency_avg_ms']:.1f} ms, "
              f"{result['requests_per_second']:.1f} req/s")

    if not first_429_at:
        print(f"  ⚠ No 429 received in {max_requests} requests")

    return result


def _parallel_download_test(service, session) -> dict:
    """Test parallel downloads to measure aggregate throughput."""
    # Find a small file to download repeatedly
    mime_clauses = " or ".join(f"mimeType='{m}'" for m in config.VIDEO_MIME_TYPES)
    query = f"({mime_clauses}) and trashed=false"

    try:
        response = service.files().list(
            corpora="drive",
            driveId=config.DRIVE_ID,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
            pageSize=10,
            q=query,
            fields=config.FILE_LIST_FIELDS,
            orderBy="quotaBytesUsed",
        ).execute()
    except Exception as e:
        return {"error": f"File listing failed: {e}"}

    files = response.get("files", [])
    small_files = [f for f in files if f.get("size") and int(f["size"]) < 50 * 1024 * 1024]
    if not small_files:
        small_files = [f for f in files if f.get("size")]
    if not small_files:
        return {"error": "No files available for download test"}

    test_file = small_files[0]
    file_id = test_file["id"]
    file_size = int(test_file["size"])
    file_name = test_file["name"]
    print(f"  Using: {file_name} ({file_size / (1024 * 1024):.1f} MB)")

    concurrency_levels = [1, 2, 4, 8]
    parallel_results = []

    for concurrency in concurrency_levels:
        # Each worker downloads the first 1 MB of the file
        download_size = min(1024 * 1024, file_size)

        def download_chunk(worker_id: int) -> dict:
            t0 = time.monotonic()
            try:
                url = f"https://www.googleapis.com/drive/v3/files/{file_id}?alt=media"
                headers = {"Range": f"bytes=0-{download_size - 1}"}
                resp = session.get(url, headers=headers)
                elapsed_ms = (time.monotonic() - t0) * 1000
                return {
                    "worker": worker_id,
                    "status": resp.status_code,
                    "bytes": len(resp.content),
                    "ms": round(elapsed_ms, 2),
                    "mbps": round((len(resp.content) / (1024 * 1024)) / (elapsed_ms / 1000), 2) if elapsed_ms > 0 else 0,
                }
            except Exception as e:
                elapsed_ms = (time.monotonic() - t0) * 1000
                return {"worker": worker_id, "error": str(e)[:200], "ms": round(elapsed_ms, 2)}

        t0_batch = time.monotonic()
        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = [executor.submit(download_chunk, i) for i in range(concurrency)]
            worker_results = [f.result() for f in as_completed(futures)]
        batch_ms = (time.monotonic() - t0_batch) * 1000

        successful = [w for w in worker_results if "error" not in w]
        aggregate_bytes = sum(w.get("bytes", 0) for w in successful)
        aggregate_mbps = (aggregate_bytes / (1024 * 1024)) / (batch_ms / 1000) if batch_ms > 0 else 0

        level_result = {
            "concurrency": concurrency,
            "successful": len(successful),
            "failed": len(worker_results) - len(successful),
            "batch_ms": round(batch_ms, 2),
            "aggregate_mbps": round(aggregate_mbps, 2),
            "per_worker": worker_results,
        }
        parallel_results.append(level_result)

        errors_count = len(worker_results) - len(successful)
        print(f"  ✓ Concurrency={concurrency}: {aggregate_mbps:.1f} MB/s aggregate, "
              f"{len(successful)}/{concurrency} success"
              f"{f', {errors_count} errors' if errors_count else ''}")

    return {
        "test_file": file_name,
        "test_file_size_mb": round(file_size / (1024 * 1024), 1),
        "download_chunk_size_mb": round(download_size / (1024 * 1024), 1),
        "levels": parallel_results,
    }


def _backoff_test(service) -> dict:
    """Deliberately trigger rate limit, then test exponential backoff recovery."""
    result = {
        "trigger_phase": {},
        "backoff_phase": {},
    }

    mime_clauses = " or ".join(f"mimeType='{m}'" for m in config.VIDEO_MIME_TYPES)
    query = f"({mime_clauses}) and trashed=false"

    # Phase 1: Rapid-fire until we hit 429
    print("  [Backoff] Phase 1: Triggering rate limit...")
    request_count = 0
    hit_429 = False

    for i in range(500):
        try:
            service.files().list(
                corpora="drive",
                driveId=config.DRIVE_ID,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                pageSize=10,
                q=query,
                fields="files(id)",
            ).execute()
            request_count += 1
        except Exception as e:
            if "429" in str(e) or "rateLimitExceeded" in str(e):
                hit_429 = True
                request_count = i + 1
                print(f"  ✓ Rate limit hit at request #{request_count}")
                break
            request_count = i + 1

    result["trigger_phase"] = {
        "requests_sent": request_count,
        "rate_limit_hit": hit_429,
    }

    if not hit_429:
        print(f"  ⚠ No 429 after {request_count} requests. Cannot test backoff.")
        result["backoff_phase"] = {"skipped": True, "reason": "rate limit not triggered"}
        return result

    # Phase 2: Exponential backoff until success
    print("  [Backoff] Phase 2: Testing exponential backoff...")
    backoff_attempts = []
    max_backoff = 64.0
    delay = 1.0
    recovered = False

    for attempt in range(10):
        print(f"  [Backoff] Attempt {attempt + 1}: waiting {delay:.1f}s...")
        time.sleep(delay)

        t0 = time.monotonic()
        try:
            service.files().list(
                corpora="drive",
                driveId=config.DRIVE_ID,
                includeItemsFromAllDrives=True,
                supportsAllDrives=True,
                pageSize=10,
                q=query,
                fields="files(id, name)",
            ).execute()
            elapsed_ms = (time.monotonic() - t0) * 1000
            backoff_attempts.append({
                "attempt": attempt + 1,
                "delay_seconds": delay,
                "result": "success",
                "latency_ms": round(elapsed_ms, 2),
            })
            recovered = True
            print(f"  ✓ Recovered after {delay:.1f}s backoff ({elapsed_ms:.1f} ms)")
            break
        except Exception as e:
            elapsed_ms = (time.monotonic() - t0) * 1000
            is_429 = "429" in str(e) or "rateLimitExceeded" in str(e)
            backoff_attempts.append({
                "attempt": attempt + 1,
                "delay_seconds": delay,
                "result": "429" if is_429 else f"error: {str(e)[:100]}",
                "latency_ms": round(elapsed_ms, 2),
            })
            print(f"  ✗ Still rate-limited after {delay:.1f}s")
            delay = min(delay * 2, max_backoff)

    result["backoff_phase"] = {
        "attempts": backoff_attempts,
        "recovered": recovered,
        "total_backoff_seconds": sum(a["delay_seconds"] for a in backoff_attempts),
    }

    return result


def _save_results(results: dict) -> None:
    log_path = config.LOG_DIR / "06_quota_stress.json"
    with open(log_path, "w") as f:
        json.dump(results, f, indent=2, default=str)
    print(f"\n[06] Results saved to {log_path}")


if __name__ == "__main__":
    run()
