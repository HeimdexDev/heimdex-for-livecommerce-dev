"""Nightly export: search_events partition → Parquet → S3 → BigQuery.

Usage:
    python -m app.cli.export_analytics                   # exports yesterday
    python -m app.cli.export_analytics --date 2026-03-06 # exports specific date
    python -m app.cli.export_analytics --dry-run         # print what would be exported

Requires pyarrow (optional dependency — only needed for export, not at API runtime).
BigQuery load requires google-cloud-bigquery (optional, gated by ANALYTICS_BQ_ENABLED).
"""

from __future__ import annotations

import argparse
import io
import json
import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export search analytics to S3 as Parquet")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Date to export (YYYY-MM-DD). Defaults to yesterday.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print what would be exported without writing to S3.",
    )
    return parser.parse_args()


def _export_date(target: date) -> tuple[datetime, datetime]:
    start = datetime(target.year, target.month, target.day, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def _rows_to_parquet(rows: list[dict[str, Any]]) -> bytes:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        logger.error("pyarrow is required for Parquet export. Install with: pip install pyarrow")
        sys.exit(1)

    if not rows:
        return b""

    schema = pa.schema(
        [
            ("id", pa.int64()),
            ("org_id", pa.string()),
            ("org_name", pa.string()),
            ("user_id", pa.string()),
            ("user_email", pa.string()),
            ("query_text", pa.string()),
            ("search_mode", pa.string()),
            ("result_count", pa.int32()),
            ("response_ms", pa.int32()),
            ("metadata", pa.string()),
            ("created_at", pa.timestamp("us", tz="UTC")),
        ]
    )

    arrays = [
        pa.array([r["id"] for r in rows], type=pa.int64()),
        pa.array([str(r["org_id"]) for r in rows], type=pa.string()),
        pa.array([r.get("org_name") for r in rows], type=pa.string()),
        pa.array([str(r["user_id"]) for r in rows], type=pa.string()),
        pa.array([r.get("user_email") for r in rows], type=pa.string()),
        pa.array([r["query_text"] for r in rows], type=pa.string()),
        pa.array([r["search_mode"] for r in rows], type=pa.string()),
        pa.array([r.get("result_count") for r in rows], type=pa.int32()),
        pa.array([r.get("response_ms") for r in rows], type=pa.int32()),
        pa.array([json.dumps(r.get("metadata", {})) for r in rows], type=pa.string()),
        pa.array([r["created_at"] for r in rows], type=pa.timestamp("us", tz="UTC")),
    ]

    table = pa.table(arrays, schema=schema)
    buf = io.BytesIO()
    pq.write_table(table, buf, compression="snappy")
    return buf.getvalue()


def _upload_to_s3(data: bytes, bucket: str, key: str, region: str) -> None:
    import boto3
    from botocore.config import Config as BotoConfig

    client = boto3.client(
        "s3",
        region_name=region,
        config=BotoConfig(retries={"max_attempts": 3, "mode": "adaptive"}),
    )
    client.put_object(Bucket=bucket, Key=key, Body=data, ContentType="application/octet-stream")
    logger.info("uploaded_to_s3", extra={"bucket": bucket, "key": key, "size_bytes": len(data)})


def _upload_to_bq(data: bytes, project: str, dataset: str, target: date) -> None:
    """Load Parquet bytes into a BQ native table via APPEND."""
    import boto3
    from google.api_core.retry import Retry
    from google.cloud import bigquery

    # google-auth's AWS provider cannot read IMDSv2 metadata inside Docker
    # containers, while boto3 handles it correctly.  Bridge boto3 credentials
    # to env vars so google-auth skips the metadata service entirely.
    session = boto3.Session()
    creds = session.get_credentials()
    if creds:
        frozen = creds.get_frozen_credentials()
        os.environ["AWS_ACCESS_KEY_ID"] = frozen.access_key
        os.environ["AWS_SECRET_ACCESS_KEY"] = frozen.secret_key
        if frozen.token:
            os.environ["AWS_SESSION_TOKEN"] = frozen.token

    client = bigquery.Client(project=project)
    table_id = f"{project}.{dataset}.search_events"

    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.PARQUET,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        # TODO: remove ALLOW_FIELD_ADDITION after BQ table has org_name+user_email columns
        schema_update_options=[bigquery.SchemaUpdateOption.ALLOW_FIELD_ADDITION],
    )

    bq_retry = Retry(initial=1.0, maximum=4.0, multiplier=2.0, deadline=30.0)

    @bq_retry
    def _do_load() -> bigquery.LoadJob:
        job = client.load_table_from_file(
            io.BytesIO(data),
            table_id,
            job_config=job_config,
        )
        job.result(timeout=60)
        return job

    load_job = _do_load()

    logger.info(
        "bq_load_complete",
        extra={"table_id": table_id, "rows": load_job.output_rows, "date": target.isoformat()},
    )


def main() -> None:
    args = _parse_args()

    if args.date:
        target = date.fromisoformat(args.date)
    else:
        target = date.today() - timedelta(days=1)

    date_from, date_to = _export_date(target)
    logger.info(f"Exporting search events for {target.isoformat()}")

    from app.config import get_settings

    settings = get_settings()

    if not settings.analytics_export_enabled:
        logger.info("ANALYTICS_EXPORT_ENABLED=false — skipping export.")
        return

    bucket = settings.analytics_s3_bucket or settings.drive_s3_bucket
    prefix = settings.analytics_s3_prefix
    s3_key = (
        f"{prefix}/search_events/"
        f"year={target.year}/month={target.month:02d}/day={target.day:02d}/"
        f"{target.isoformat()}.parquet"
    )

    if args.dry_run:
        logger.info(f"[DRY RUN] Would export to s3://{bucket}/{s3_key}")
        return

    import asyncio
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
    from app.db.base import get_async_engine
    import app.db.models  # noqa: F401 — register all models for relationship resolution
    from app.modules.search.search_event_repository import SearchEventRepository

    async def _fetch_events() -> list[dict[str, Any]]:
        engine = get_async_engine()
        factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
        async with factory() as session:
            repo = SearchEventRepository(session)
            rows = await repo.list_by_date_range_with_labels(
                date_from=date_from,
                date_to=date_to,
            )
            return [
                {
                    "id": e.id,
                    "org_id": e.org_id,
                    "org_name": org_name,
                    "user_id": e.user_id,
                    "user_email": user_email,
                    "query_text": e.query_text,
                    "search_mode": e.search_mode,
                    "result_count": e.result_count,
                    "response_ms": e.response_ms,
                    "metadata": e.metadata_,
                    "created_at": e.created_at,
                }
                for e, org_name, user_email in rows
            ]

    rows = asyncio.run(_fetch_events())
    logger.info(f"Fetched {len(rows)} events for {target.isoformat()}")

    if not rows:
        logger.info("No events to export — skipping S3 upload.")
        return

    parquet_data = _rows_to_parquet(rows)
    logger.info(f"Parquet size: {len(parquet_data):,} bytes ({len(rows)} rows)")

    _upload_to_s3(parquet_data, bucket, s3_key, settings.s3_region)
    logger.info(f"Export complete: s3://{bucket}/{s3_key}")

    if settings.analytics_bq_enabled:
        if not settings.analytics_bq_project:
            logger.error("ANALYTICS_BQ_PROJECT is required when ANALYTICS_BQ_ENABLED=true")
        else:
            try:
                _upload_to_bq(
                    parquet_data,
                    settings.analytics_bq_project,
                    settings.analytics_bq_dataset,
                    target,
                )
            except Exception as exc:
                # Predictable failure when GCP Workload Identity Federation
                # isn't wired (no GOOGLE_APPLICATION_CREDENTIALS / external_account
                # JSON / WIF pool — see project_prod_bq_federation_unwired.md).
                # Match by class name to avoid a hard module-level dependency on
                # google.auth.exceptions; this keeps the test allowlist independent
                # of optional google-cloud-bigquery installation.
                if type(exc).__name__ == "DefaultCredentialsError":
                    logger.warning(
                        "bq_load_skipped_no_credentials",
                        extra={
                            "project": settings.analytics_bq_project,
                            "remediation": (
                                "Wire GCP Workload Identity Federation + set "
                                "GOOGLE_APPLICATION_CREDENTIALS on the api container, "
                                "or set ANALYTICS_BQ_ENABLED=false to silence."
                            ),
                        },
                    )
                else:
                    logger.exception("BQ load failed — S3 upload was successful, continuing")


if __name__ == "__main__":
    main()
