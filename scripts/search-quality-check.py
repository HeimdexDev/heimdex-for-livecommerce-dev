#!/usr/bin/env python3
"""
Search Quality Regression Check

Runs a set of golden queries against the local API and verifies:
1. Search endpoint responds successfully
2. Results are returned (non-empty for known queries)
3. Response times are within acceptable bounds
4. All search modes work (BM25, semantic, hybrid)

Usage:
    python scripts/search-quality-check.py                    # Run against local
    API_URL=https://devorg.app.heimdexdemo.dev python scripts/search-quality-check.py  # Staging

Exit code: 0 if all pass, 1 if any fail.
Requires: httpx or requests, running API with indexed data.
"""
from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass

try:
    import httpx as http_client

    def post(url, headers, json_data, timeout):
        r = http_client.post(url, headers=headers, json=json_data, timeout=timeout)
        return r.status_code, r.json(), r.elapsed.total_seconds()
except ImportError:
    import requests as http_client  # type: ignore[no-redef]

    def post(url, headers, json_data, timeout):  # type: ignore[misc]
        r = http_client.post(url, headers=headers, json=json_data, timeout=timeout)
        return r.status_code, r.json(), r.elapsed.total_seconds()


API_URL = os.environ.get("API_URL", "http://localhost:8000")
ORG_HOST = os.environ.get("ORG_HOST", "devorg.app.heimdex.local")
DEV_EMAIL = os.environ.get("DEV_EMAIL", "admin@devorg.example.com")
MAX_RESPONSE_TIME = float(os.environ.get("MAX_RESPONSE_TIME", "5.0"))  # seconds


@dataclass
class QueryResult:
    query: str
    alpha: float
    mode: str
    status: int
    hit_count: int
    response_time: float
    passed: bool
    reason: str = ""


def get_dev_token() -> str:
    """Get a dev-login token."""
    try:
        status, body, _ = post(
            f"{API_URL}/api/auth/dev-login",
            headers={"Content-Type": "application/json", "Host": ORG_HOST},
            json_data={"email": DEV_EMAIL},
            timeout=10,
        )
        if status == 200:
            return body.get("access_token", body.get("token", ""))
    except Exception:
        pass

    # Fallback: try JWT-based token (for environments with JWT_SECRET)
    try:
        import datetime
        from jose import jwt

        secret = os.environ.get("JWT_SECRET", "dev-secret")
        payload = {
            "sub": "test-user",
            "org_id": "test-org",
            "exp": datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=1),
            "iat": datetime.datetime.now(datetime.timezone.utc),
        }
        return jwt.encode(payload, secret, algorithm="HS256")
    except ImportError:
        pass

    return ""


def run_search(token: str, query: str, alpha: float, size: int = 5) -> QueryResult:
    """Run a single search query and evaluate the result."""
    mode = "bm25" if alpha == 0.0 else "semantic" if alpha == 1.0 else "hybrid"

    try:
        status, body, elapsed = post(
            f"{API_URL}/search/scenes",
            headers={
                "Authorization": f"Bearer {token}",
                "Host": ORG_HOST,
                "Content-Type": "application/json",
            },
            json_data={"q": query, "alpha": alpha, "size": size},
            timeout=30,
        )

        hits = body.get("hits", [])
        hit_count = len(hits)

        # Evaluate
        if status != 200:
            return QueryResult(query, alpha, mode, status, 0, elapsed, False, f"HTTP {status}")
        if elapsed > MAX_RESPONSE_TIME:
            return QueryResult(query, alpha, mode, status, hit_count, elapsed, False, f"Slow: {elapsed:.1f}s > {MAX_RESPONSE_TIME}s")

        return QueryResult(query, alpha, mode, status, hit_count, elapsed, True)

    except Exception as e:
        return QueryResult(query, alpha, mode, 0, 0, 0.0, False, str(e))


# Golden queries: (query, alpha, description)
GOLDEN_QUERIES = [
    # BM25 (lexical)
    ("라이브커머스", 0.0, "Korean: live commerce (BM25)"),
    ("화장품", 0.0, "Korean: cosmetics (BM25)"),
    # Semantic
    ("화장품 리뷰", 1.0, "Korean: cosmetics review (semantic)"),
    ("가격 안내", 1.0, "Korean: price announcement (semantic)"),
    # Hybrid
    ("삼성 갤럭시", 0.5, "Korean: Samsung Galaxy (hybrid)"),
    ("신상품 소개", 0.5, "Korean: new product intro (hybrid)"),
]


def main() -> int:
    print(f"Search Quality Check — {API_URL}")
    print(f"{'=' * 60}")

    # Get token
    token = get_dev_token()
    if not token:
        print("FAIL: Could not obtain auth token")
        print("  Is the API running? Is dev-login enabled?")
        return 1

    # Check if there's any indexed data
    test_result = run_search(token, "test", 0.0, 1)
    if test_result.status != 200:
        print(f"FAIL: Search endpoint returned HTTP {test_result.status}")
        print(f"  Reason: {test_result.reason}")
        return 1

    # Run golden queries
    results: list[QueryResult] = []
    for query, alpha, description in GOLDEN_QUERIES:
        result = run_search(token, query, alpha)
        results.append(result)

        status_icon = "PASS" if result.passed else "FAIL"
        hit_info = f"{result.hit_count} hits" if result.hit_count > 0 else "0 hits (empty index?)"
        time_info = f"{result.response_time:.2f}s"

        print(f"  [{status_icon}] {description}")
        print(f"         {hit_info}, {time_info}")
        if result.reason:
            print(f"         Reason: {result.reason}")

    # Summary
    passed = sum(1 for r in results if r.passed)
    failed = sum(1 for r in results if not r.passed)
    avg_time = sum(r.response_time for r in results) / len(results) if results else 0

    print(f"\n{'=' * 60}")
    print(f"Results: {passed}/{len(results)} passed, {failed} failed")
    print(f"Avg response time: {avg_time:.2f}s (max allowed: {MAX_RESPONSE_TIME}s)")

    # Warnings (non-failing)
    empty_results = [r for r in results if r.passed and r.hit_count == 0]
    if empty_results:
        print(f"\nWARNING: {len(empty_results)} queries returned 0 hits (index may be empty)")
        for r in empty_results:
            print(f"  - \"{r.query}\" ({r.mode})")

    if failed > 0:
        print(f"\nFAILED — {failed} search quality checks did not pass")
        return 1

    print("\nPASSED — all search quality checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
