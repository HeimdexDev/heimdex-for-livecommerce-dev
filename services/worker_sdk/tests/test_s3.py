"""Tests for heimdex_worker_sdk.s3 — S3Client construction and _build_s3_client."""

from unittest.mock import MagicMock, patch

import pytest

from heimdex_worker_sdk.s3 import S3Client, _build_s3_client


class TestS3ClientConstruction:
    """Verify S3Client accepts the same interface as app.storage.s3.S3Client."""

    def test_with_explicit_client(self):
        mock_client = MagicMock()
        s3 = S3Client(bucket="test-bucket", client=mock_client)
        assert s3.bucket == "test-bucket"
        assert s3._client is mock_client

    def test_bucket_property(self):
        mock_client = MagicMock()
        s3 = S3Client(bucket="my-bucket", client=mock_client)
        assert s3.bucket == "my-bucket"


class TestBuildS3Client:
    """Verify _build_s3_client reads from WorkerSettings (not app.config)."""

    def test_build_uses_worker_settings(self):
        _build_s3_client.cache_clear()

        mock_settings = MagicMock()
        mock_settings.minio_secure = False
        mock_settings.minio_endpoint = "minio:9000"
        mock_settings.minio_access_key = "testkey"
        mock_settings.minio_secret_key = "testsecret"

        with patch("heimdex_worker_sdk.s3.get_worker_settings", return_value=mock_settings):
            with patch("heimdex_worker_sdk.s3.boto3") as mock_boto3:
                client = _build_s3_client()
                mock_boto3.client.assert_called_once()
                call_kwargs = mock_boto3.client.call_args
                assert call_kwargs[1]["endpoint_url"] == "http://minio:9000"
                assert call_kwargs[1]["aws_access_key_id"] == "testkey"
                assert call_kwargs[1]["aws_secret_access_key"] == "testsecret"

        _build_s3_client.cache_clear()

    def test_build_uses_https_when_secure(self):
        _build_s3_client.cache_clear()

        mock_settings = MagicMock()
        mock_settings.minio_secure = True
        mock_settings.minio_endpoint = "s3.amazonaws.com"
        mock_settings.minio_access_key = "key"
        mock_settings.minio_secret_key = "secret"

        with patch("heimdex_worker_sdk.s3.get_worker_settings", return_value=mock_settings):
            with patch("heimdex_worker_sdk.s3.boto3") as mock_boto3:
                client = _build_s3_client()
                call_kwargs = mock_boto3.client.call_args
                assert call_kwargs[1]["endpoint_url"] == "https://s3.amazonaws.com"

        _build_s3_client.cache_clear()


class TestS3ClientMethods:
    """Verify S3Client method signatures match app.storage.s3.S3Client."""

    def test_has_all_methods(self):
        mock_client = MagicMock()
        s3 = S3Client(bucket="test", client=mock_client)

        assert callable(s3.ensure_bucket)
        assert callable(s3.upload_file)
        assert callable(s3.download_file)
        assert callable(s3.get_object_bytes)
        assert callable(s3.exists)
        assert callable(s3.generate_presigned_url)
        assert callable(s3.delete)
        assert callable(s3.delete_prefix)

    def test_exists_delegates_to_client(self):
        mock_client = MagicMock()
        s3 = S3Client(bucket="test-bucket", client=mock_client)
        s3.exists("some/key")
        mock_client.head_object.assert_called_once_with(
            Bucket="test-bucket", Key="some/key",
        )

    def test_delete_delegates_to_client(self):
        mock_client = MagicMock()
        s3 = S3Client(bucket="test-bucket", client=mock_client)
        s3.delete("some/key")
        mock_client.delete_object.assert_called_once_with(
            Bucket="test-bucket", Key="some/key",
        )
