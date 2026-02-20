"""Tests for S3 boto3 client singleton lifecycle.

boto3 is not in the API test venv, so we mock it at the module level.
"""
import sys
from unittest.mock import MagicMock

import pytest

from app.config import Settings

_mock_boto3 = MagicMock()
_mock_botocore = MagicMock()


@pytest.fixture(autouse=True)
def _patch_boto3(monkeypatch):
    monkeypatch.setitem(sys.modules, "boto3", _mock_boto3)
    monkeypatch.setitem(sys.modules, "botocore", _mock_botocore)
    monkeypatch.setitem(sys.modules, "botocore.config", _mock_botocore.config)

    _mock_boto3.client.reset_mock()
    _mock_boto3.client.return_value = MagicMock(name="shared_s3_client")

    if "app.storage.s3" in sys.modules:
        del sys.modules["app.storage.s3"]

    yield

    if "app.storage.s3" in sys.modules:
        del sys.modules["app.storage.s3"]


def test_build_s3_client_returns_singleton():
    from app.storage.s3 import _build_s3_client

    _build_s3_client.cache_clear()
    client_a = _build_s3_client()
    client_b = _build_s3_client()

    assert client_a is client_b
    _mock_boto3.client.assert_called_once()
    _build_s3_client.cache_clear()


def test_s3client_instances_share_boto3_client():
    from app.storage.s3 import S3Client, _build_s3_client

    _build_s3_client.cache_clear()
    s3_drive = S3Client(bucket="heimdex-drive")
    s3_export = S3Client(bucket="heimdex-exports")

    assert s3_drive._client is s3_export._client
    _mock_boto3.client.assert_called_once()
    _build_s3_client.cache_clear()


def test_s3client_with_injected_client_skips_singleton():
    from app.storage.s3 import S3Client

    custom_client = MagicMock()
    s3 = S3Client(bucket="test", client=custom_client)
    assert s3._client is custom_client
