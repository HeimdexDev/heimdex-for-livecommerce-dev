"""S3/MinIO client for the API.

Supports two modes based on ``Settings.minio_endpoint``:
  - **MinIO mode** (default): ``minio_endpoint`` is set → connects to a
    MinIO-compatible endpoint with explicit credentials.
  - **AWS S3 mode**: ``minio_endpoint`` is empty → uses the default boto3
    credential chain (env vars, IAM role) and the real AWS S3 endpoint.
"""
import asyncio
import logging
from functools import lru_cache, partial
from pathlib import Path
from typing import Optional

import boto3
from botocore.config import Config as BotoConfig
from app.config import get_settings

logger = logging.getLogger(__name__)


# Sentinel values that mean "no MinIO, use real AWS S3".
# Needed because some container platforms (e.g. AirCloud+) cannot
# set truly empty env vars, so the default 'localhost:9000' persists.
_MINIO_DISABLED_SENTINELS = {"", "none", "disabled"}


def _use_real_s3(endpoint: str) -> bool:
    """Return True when the S3 client should use real AWS S3."""
    return endpoint.strip().lower() in _MINIO_DISABLED_SENTINELS


@lru_cache(maxsize=1)
def _build_s3_client():
    settings = get_settings()
    if not _use_real_s3(settings.minio_endpoint):
        # MinIO / S3-compatible mode
        boto_config = BotoConfig(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "adaptive"},
            s3={"addressing_style": "path"},
        )
        client = boto3.client(
            "s3",
            endpoint_url=f"{'https' if settings.minio_secure else 'http'}://{settings.minio_endpoint}",
            aws_access_key_id=settings.minio_access_key,
            aws_secret_access_key=settings.minio_secret_key,
            config=boto_config,
            region_name="us-east-1",
        )
    else:
        # Real AWS S3 mode — credentials from env/IAM
        boto_config = BotoConfig(
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "adaptive"},
        )
        client = boto3.client(
            "s3",
            config=boto_config,
            region_name=settings.s3_region,
        )

    use_s3 = _use_real_s3(settings.minio_endpoint)
    logger.info(
        "s3_client_initialized",
        extra={
            "mode": "aws-s3" if use_s3 else "minio",
            "region": settings.s3_region if use_s3 else "us-east-1",
        },
    )
    return client


class S3Client:
    """Generic S3/MinIO client.

    Parameters
    ----------
    bucket:
        Target bucket name (required — no hidden defaults).
    client:
        Optional pre-built boto3 client (useful for testing).
    """

    def __init__(self, bucket: str, client=None):
        self._client = client or _build_s3_client()
        self._bucket = bucket

    @property
    def bucket(self) -> str:
        return self._bucket

    def ensure_bucket(self) -> None:
        """Create the bucket if it does not exist."""
        try:
            self._client.head_bucket(Bucket=self._bucket)
        except self._client.exceptions.ClientError:
            self._client.create_bucket(Bucket=self._bucket)
            logger.info("s3_bucket_created", extra={"bucket": self._bucket})

    def upload_file(
        self,
        local_path: Path,
        s3_key: str,
        content_type: str = "application/octet-stream",
    ) -> None:
        """Upload a local file to S3."""
        self._client.upload_file(
            str(local_path),
            self._bucket,
            s3_key,
            ExtraArgs={"ContentType": content_type},
        )
        logger.info(
            "s3_uploaded",
            extra={"key": s3_key, "size": local_path.stat().st_size},
        )

    def download_file(self, s3_key: str, local_path: Path) -> None:
        """Download an S3 object to a local file."""
        local_path.parent.mkdir(parents=True, exist_ok=True)
        self._client.download_file(self._bucket, s3_key, str(local_path))

    def get_object_bytes(self, s3_key: str) -> Optional[bytes]:
        """Return object contents as bytes, or ``None`` if the key does not exist.

        Raises on S3 connectivity or permission errors so callers can
        distinguish "key missing" from "S3 unavailable".
        """
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=s3_key)
            return response["Body"].read()
        except self._client.exceptions.NoSuchKey:
            return None
        except self._client.exceptions.ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchKey"):
                return None
            raise

    def exists(self, s3_key: str) -> bool:
        """Check whether an S3 key exists.

        Returns False only when the key genuinely does not exist (404).
        Raises on S3 connectivity or permission errors.
        """
        try:
            self._client.head_object(Bucket=self._bucket, Key=s3_key)
            return True
        except self._client.exceptions.ClientError as exc:
            error_code = exc.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchKey"):
                return False
            raise

    def generate_presigned_url(self, s3_key: str, expires_in: int = 3600) -> str:
        """Generate a presigned GET URL."""
        return self._client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self._bucket, "Key": s3_key},
            ExpiresIn=expires_in,
        )

    def delete(self, s3_key: str) -> None:
        """Delete a single object."""
        self._client.delete_object(Bucket=self._bucket, Key=s3_key)

    # --- Async wrappers for use in FastAPI endpoints ---

    async def get_object_bytes_async(self, s3_key: str) -> Optional[bytes]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.get_object_bytes, s3_key)

    async def download_file_async(self, s3_key: str, local_path: Path) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self.download_file, s3_key, local_path)

    async def exists_async(self, s3_key: str) -> bool:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.exists, s3_key)

    async def generate_presigned_url_async(self, s3_key: str, expires_in: int = 3600) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, partial(self.generate_presigned_url, s3_key, expires_in)
        )

    async def upload_file_async(
        self, local_path: Path, s3_key: str, content_type: str = "application/octet-stream"
    ) -> None:
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None, partial(self.upload_file, local_path, s3_key, content_type)
        )

    def delete_prefix(self, prefix: str) -> int:
        """Delete all objects under *prefix*. Returns count of deleted objects."""
        deleted = 0
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self._bucket, Prefix=prefix):
            objects = page.get("Contents", [])
            if not objects:
                continue
            self._client.delete_objects(
                Bucket=self._bucket,
                Delete={"Objects": [{"Key": obj["Key"]} for obj in objects]},
            )
            deleted += len(objects)
        return deleted
