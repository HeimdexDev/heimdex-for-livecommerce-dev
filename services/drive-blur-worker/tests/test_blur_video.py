"""Worker-side tests for ``src.tasks.blur_video``.

Covers the handler's plumbing without booting transformers, torch,
insightface, or real SQS / S3 / HTTP:

* ``sqs_to_blur_claim`` parses both dict bodies and SQS-style objects
* ``process_blur_message`` happy path: claim → download → run → upload →
  complete
* Claim 409 (cancelled) short-circuits without running the pipeline
* Pipeline exception → complete(status=failed) fired, then re-raised so
  SQS redelivers
* Cancel-mid-run: complete response says cleanup_required → uploaded
  S3 keys are deleted
* ``_apply_options_to_pipeline`` only mutates the allow-listed fields

Run via ``pytest services/drive-blur-worker/tests/`` once the worker
container volume mounts are wired — or directly on the host with
``heimdex-worker-sdk``, ``heimdex-media-contracts``, and
``heimdex-media-pipelines`` installed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID, uuid4

import pytest

# Make ``src`` importable without packaging the worker as a pip module.
_WORKER_ROOT = Path(__file__).resolve().parent.parent
if str(_WORKER_ROOT) not in sys.path:
    sys.path.insert(0, str(_WORKER_ROOT))

from src.tasks.blur_video import (  # noqa: E402
    BlurClaimRef,
    _apply_options_to_pipeline,
    process_blur_message,
    sqs_to_blur_claim,
)

# These tests use ``@patch("heimdex_worker_sdk.s3.S3Client")`` which
# requires the real SDK module (with its ``s3`` submodule) to be
# importable — the patch target is resolved via attribute lookup, not
# the mocked sys.modules entry. On a bare laptop without the real
# worker SDK installed, the imports succeed (via docker-compose
# volume mount) but this top-level attribute path doesn't exist, so
# pytest bails with ``AttributeError: module 'heimdex_worker_sdk' has
# no attribute 's3'``.
#
# The newer ``test_blur_video_integration.py`` uses a different stub
# strategy (``monkeypatch.setitem(sys.modules, ...)``) that runs on
# any host. These class-based tests stay for in-container runs where
# the real SDK is present.
try:
    import heimdex_worker_sdk.s3  # noqa: F401
    _HAS_WORKER_SDK = True
except Exception:
    _HAS_WORKER_SDK = False

pytestmark = pytest.mark.skipif(
    not _HAS_WORKER_SDK,
    reason="heimdex_worker_sdk.s3 not importable on this host — run inside the worker container or see test_blur_video_integration.py",
)


# ---------- fixtures ----------


def _claim_ref(**overrides) -> BlurClaimRef:
    base = dict(
        job_id=uuid4(),
        org_id=uuid4(),
        file_id=uuid4(),
        video_id="gd_testvideo",
    )
    base.update(overrides)
    return BlurClaimRef(**base)


def _settings():
    return SimpleNamespace(drive_s3_bucket="heimdex-drive")


def _stub_pipeline():
    """A pipeline double that writes a tiny file on ``process_video`` and
    returns a ``BlurResult``-shaped namespace with ``to_manifest`` and
    ``summary`` callables.
    """
    pipeline = MagicMock()
    pipeline.config = SimpleNamespace(
        do_faces=True,
        do_owl=True,
        owl_stride=5,
        owl_score_threshold=0.35,
        min_face_confidence=0.5,
        mosaic_cells=100,
        feather=3,
        categories=("face", "license_plate", "card_object"),
    )

    def _process(in_path, out_path):
        Path(out_path).write_bytes(b"blurred-mp4-stub")
        result = MagicMock()
        result.frame_count = 42
        result.total_ms = 1234.5
        result.owl_infer_ms = 900.0
        result.to_manifest = MagicMock(return_value={
            "schema_version": "1",
            "video": {"fps": 25.0, "width": 640, "height": 360, "frame_count": 42},
            "detections": [],
            "summary": {"face": 2},
        })
        result.summary = MagicMock(return_value={"face": 2})
        return result

    pipeline.process_video = MagicMock(side_effect=_process)
    return pipeline


def _stub_s3():
    s3 = MagicMock()
    s3.bucket = "heimdex-drive"
    s3._client = MagicMock()

    def _download(key, local_path):
        Path(local_path).write_bytes(b"fake-source-mp4")

    s3.download_file = MagicMock(side_effect=_download)
    s3.upload_file = MagicMock()
    s3.delete = MagicMock()
    return s3


def _http_response(status_code: int, json_body: dict | None = None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = json.dumps(json_body or {})
    resp.json = MagicMock(return_value=json_body or {})
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = RuntimeError(f"HTTP {status_code}")
    return resp


# ---------- sqs_to_blur_claim ----------


class TestSqsAdapter:
    def test_parses_dict_message(self):
        body = {
            "job_id": str(uuid4()),
            "org_id": str(uuid4()),
            "file_id": str(uuid4()),
            "video_id": "gd_video",
            "source_s3_key": "proxies/gd_video/proxy.mp4",
            "source_kind": "proxy",
            "options": {},
        }
        msg = SimpleNamespace(body=json.dumps(body))
        ref = sqs_to_blur_claim(msg)
        assert isinstance(ref, BlurClaimRef)
        assert ref.video_id == "gd_video"
        assert isinstance(ref.job_id, UUID)

    def test_parses_sqs_style_mapping(self):
        body = {
            "job_id": str(uuid4()),
            "org_id": str(uuid4()),
            "file_id": str(uuid4()),
            "video_id": "gd_video",
        }
        msg = {"Body": json.dumps(body)}
        ref = sqs_to_blur_claim(msg)
        assert ref.video_id == "gd_video"


# ---------- process_blur_message happy path ----------


class TestHappyPath:
    def test_claim_download_run_upload_complete(self):
        ref = _claim_ref()
        pipeline = _stub_pipeline()
        s3 = _stub_s3()
        lease_token = str(uuid4())

        claim_resp = _http_response(200, {
            "id": str(ref.job_id),
            "org_id": str(ref.org_id),
            "file_id": str(ref.file_id),
            "video_id": ref.video_id,
            "source_s3_key": "proxies/gd_testvideo/proxy.mp4",
            "source_kind": "proxy",
            "options": {"do_faces": True, "owl_stride": 5},
            "lease_token": lease_token,
            "lease_expires_at": "2026-04-14T12:00:00Z",
        })
        complete_resp = _http_response(200, {
            "ok": True, "job_id": str(ref.job_id), "status": "done",
        })

        with patch("src.tasks.blur_video.requests.post",
                   side_effect=[claim_resp, complete_resp]) as mock_post, \
             patch("heimdex_worker_sdk.s3.S3Client", return_value=s3):
            process_blur_message(
                api_base_url="http://api:8000",
                internal_api_key="tok",
                settings=_settings(),
                claim_ref=ref,
                pipeline=pipeline,
            )

        # 1. claim + complete — exactly two POSTs.
        assert mock_post.call_count == 2
        claim_call, complete_call = mock_post.call_args_list
        assert f"/internal/blur/{ref.job_id}/claim" in claim_call.args[0]
        assert f"/internal/blur/{ref.job_id}/complete" in complete_call.args[0]

        # 2. Source downloaded from the claim response, not the message.
        s3.download_file.assert_called_once()
        assert s3.download_file.call_args.args[0] == "proxies/gd_testvideo/proxy.mp4"

        # 3. Pipeline invoked.
        pipeline.process_video.assert_called_once()

        # 4. Per-job S3 keys.
        s3.upload_file.assert_called_once()
        upload_key = s3.upload_file.call_args.args[1]
        assert upload_key == f"blurred/{ref.video_id}/{ref.job_id}/blurred.mp4"

        # 5. Manifest uploaded via put_object under the per-job prefix.
        put_kwargs = s3._client.put_object.call_args.kwargs
        assert put_kwargs["Key"] == f"blurred/{ref.video_id}/{ref.job_id}/manifest.json"
        assert put_kwargs["ContentType"] == "application/json"
        manifest_bytes = put_kwargs["Body"]
        parsed = json.loads(manifest_bytes.decode())
        assert parsed["summary"] == {"face": 2}

        # 6. Complete payload carries the lease token and summary.
        complete_body = json.loads(complete_call.kwargs["data"])
        assert complete_body["lease_token"] == lease_token
        assert complete_body["status"] == "done"
        assert complete_body["detections_summary"] == {"face": 2}


# ---------- 409 on claim ----------


class TestClaimConflict:
    def test_claim_409_skips_pipeline(self):
        ref = _claim_ref()
        pipeline = _stub_pipeline()
        s3 = _stub_s3()
        claim_resp = _http_response(409, {"detail": "Blur job was cancelled"})

        with patch("src.tasks.blur_video.requests.post",
                   side_effect=[claim_resp]) as mock_post, \
             patch("heimdex_worker_sdk.s3.S3Client", return_value=s3):
            process_blur_message(
                api_base_url="http://api:8000",
                internal_api_key="tok",
                settings=_settings(),
                claim_ref=ref,
                pipeline=pipeline,
            )
        assert mock_post.call_count == 1
        pipeline.process_video.assert_not_called()
        s3.download_file.assert_not_called()
        s3.upload_file.assert_not_called()


# ---------- pipeline exception → failed ----------


class TestPipelineFailure:
    def test_exception_reports_failed_and_reraises(self):
        ref = _claim_ref()
        pipeline = _stub_pipeline()
        pipeline.process_video.side_effect = RuntimeError("OOM")
        s3 = _stub_s3()
        lease_token = str(uuid4())

        claim_resp = _http_response(200, {
            "id": str(ref.job_id),
            "org_id": str(ref.org_id),
            "file_id": str(ref.file_id),
            "video_id": ref.video_id,
            "source_s3_key": "proxies/gd_testvideo/proxy.mp4",
            "source_kind": "proxy",
            "options": {},
            "lease_token": lease_token,
            "lease_expires_at": "2026-04-14T12:00:00Z",
        })
        failed_resp = _http_response(200, {"ok": True, "status": "failed"})

        with patch("src.tasks.blur_video.requests.post",
                   side_effect=[claim_resp, failed_resp]) as mock_post, \
             patch("heimdex_worker_sdk.s3.S3Client", return_value=s3):
            with pytest.raises(RuntimeError, match="OOM"):
                process_blur_message(
                    api_base_url="http://api:8000",
                    internal_api_key="tok",
                    settings=_settings(),
                    claim_ref=ref,
                    pipeline=pipeline,
                )

        assert mock_post.call_count == 2
        fail_call = mock_post.call_args_list[1]
        body = json.loads(fail_call.kwargs["data"])
        assert body["status"] == "failed"
        assert body["lease_token"] == lease_token
        assert "OOM" in body["error"]
        # No upload on failure path.
        s3.upload_file.assert_not_called()


# ---------- cancel mid-run ----------


class TestCancelMidRun:
    def test_cleanup_required_deletes_s3_outputs(self):
        ref = _claim_ref()
        pipeline = _stub_pipeline()
        s3 = _stub_s3()
        lease_token = str(uuid4())

        claim_resp = _http_response(200, {
            "id": str(ref.job_id),
            "org_id": str(ref.org_id),
            "file_id": str(ref.file_id),
            "video_id": ref.video_id,
            "source_s3_key": "proxies/gd_testvideo/proxy.mp4",
            "source_kind": "proxy",
            "options": {},
            "lease_token": lease_token,
            "lease_expires_at": "2026-04-14T12:00:00Z",
        })
        cancel_resp = _http_response(200, {
            "ok": False,
            "job_id": str(ref.job_id),
            "reason": "cancelled",
            "cleanup_required": True,
        })

        with patch("src.tasks.blur_video.requests.post",
                   side_effect=[claim_resp, cancel_resp]), \
             patch("heimdex_worker_sdk.s3.S3Client", return_value=s3):
            process_blur_message(
                api_base_url="http://api:8000",
                internal_api_key="tok",
                settings=_settings(),
                claim_ref=ref,
                pipeline=pipeline,
            )

        # Both per-job objects must be deleted after the cancel response.
        deleted_keys = [c.args[0] for c in s3.delete.call_args_list]
        assert f"blurred/{ref.video_id}/{ref.job_id}/blurred.mp4" in deleted_keys
        assert f"blurred/{ref.video_id}/{ref.job_id}/manifest.json" in deleted_keys


# ---------- options allowlist ----------


class TestOptionsAllowlist:
    def test_applies_known_fields(self):
        cfg = SimpleNamespace(
            do_faces=True,
            do_owl=True,
            owl_stride=5,
            owl_score_threshold=0.35,
            min_face_confidence=0.5,
            mosaic_cells=100,
            feather=3,
            categories=("face",),
        )
        pipeline = SimpleNamespace(config=cfg)
        _apply_options_to_pipeline(pipeline, {
            "do_faces": False,
            "owl_stride": 10,
            "owl_score_threshold": 0.5,
            "categories": ["license_plate", "card_object"],
        })
        assert cfg.do_faces is False
        assert cfg.owl_stride == 10
        assert cfg.owl_score_threshold == 0.5
        assert cfg.categories == ("license_plate", "card_object")

    def test_ignores_unknown_fields(self):
        cfg = SimpleNamespace(
            do_faces=True,
            do_owl=True,
            owl_stride=5,
            owl_score_threshold=0.35,
            min_face_confidence=0.5,
            mosaic_cells=100,
            feather=3,
            categories=("face",),
        )
        pipeline = SimpleNamespace(config=cfg)
        # ``owl_model`` is deliberately not in the allow-list because
        # switching models would require reloading OWLv2 weights; the
        # handler must drop it silently.
        _apply_options_to_pipeline(pipeline, {
            "owl_model": "different/model",
            "random_field": 123,
        })
        # Unchanged.
        assert not hasattr(cfg, "owl_model")
        assert not hasattr(cfg, "random_field")
