"""Backfill capture_time in OpenSearch for videos missing google_created_time.

For files where google_created_time is NULL, uses google_modified_time
as the best available fallback. Updates both the DB and OpenSearch.

Usage (pipe into API container on staging):
    cat scripts/backfill-created-time.py | ssh -i ~/.ssh/heimdex-staging.pem \
        ec2-user@3.34.75.63 "cd /opt/heimdex/dev-heimdex-for-livecommerce && \
        docker compose exec -T api python -"
"""

import logging
import os
import sys

import psycopg2
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

API_BASE = os.environ.get("INTERNAL_API_URL", "http://localhost:8000")
API_KEY = os.environ.get("DRIVE_INTERNAL_API_KEY", "")


def _sync_db_url(db_url: str) -> str:
    """Convert async SQLAlchemy URL to psycopg2-compatible URL."""
    return db_url.replace("postgresql+asyncpg://", "postgresql://")


def get_files_needing_backfill(db_url: str) -> list[dict]:
    """Find files where google_created_time is NULL but google_modified_time exists."""
    conn = psycopg2.connect(_sync_db_url(db_url))
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT video_id, file_name, org_id::text,
                       google_modified_time
                FROM drive_files
                WHERE google_created_time IS NULL
                  AND google_modified_time IS NOT NULL
                  AND is_deleted = false
                ORDER BY created_at DESC
            """)
            columns = [desc[0] for desc in cur.description]
            return [dict(zip(columns, row)) for row in cur.fetchall()]
    finally:
        conn.close()


def update_db_created_time(video_id: str, modified_time: str, db_url: str) -> bool:
    """Set google_created_time = google_modified_time as fallback."""
    conn = psycopg2.connect(_sync_db_url(db_url))
    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE drive_files
                   SET google_created_time = google_modified_time
                   WHERE video_id = %s AND google_created_time IS NULL""",
                (video_id,),
            )
            updated = cur.rowcount
            conn.commit()
            return updated > 0
    finally:
        conn.close()


def update_opensearch(video_id: str, capture_time: str, org_id: str) -> int:
    """Update capture_time in OpenSearch scenes via internal API."""
    url = f"{API_BASE}/internal/drive/sync/backfill-capture-time"
    headers = {
        "Content-Type": "application/json",
        "X-Heimdex-Org-Id": org_id,
    }
    if API_KEY:
        headers["Authorization"] = f"Bearer {API_KEY}"

    try:
        resp = requests.post(
            url,
            json={"video_id": video_id, "capture_time": capture_time},
            headers=headers,
            timeout=30,
        )
        if resp.status_code == 404:
            logger.warning(f"  OS_SKIP {video_id} — endpoint not found")
            return 0
        resp.raise_for_status()
        return resp.json().get("updated", 0)
    except Exception as e:
        logger.warning(f"  OS_ERROR {video_id}: {e}")
        return 0


def main():
    db_url = os.environ.get("DATABASE_URL", "")
    if not db_url:
        logger.error("DATABASE_URL not set")
        sys.exit(1)

    logger.info("Finding files missing google_created_time...")
    files = get_files_needing_backfill(db_url)

    if not files:
        logger.info("No files need backfill")
        return

    logger.info(f"Found {len(files)} files to backfill")

    db_count = 0
    os_count = 0

    for f in files:
        video_id = f["video_id"]
        file_name = f["file_name"]
        org_id = f["org_id"]
        modified_time = f["google_modified_time"].isoformat()

        # 1. Update DB: set google_created_time = google_modified_time
        if update_db_created_time(video_id, modified_time, db_url):
            db_count += 1

        # 2. Update OpenSearch capture_time
        scenes = update_opensearch(video_id, modified_time, org_id)
        if scenes > 0:
            os_count += 1
            logger.info(f"  OK {video_id} ({file_name}) → {modified_time} ({scenes} scenes)")
        else:
            logger.info(f"  DB_ONLY {video_id} ({file_name}) → {modified_time} (no scenes in index)")

    logger.info(f"Backfill complete: {db_count} DB rows, {os_count} videos in OpenSearch, {len(files)} total")


if __name__ == "__main__":
    main()
