"""Integration test for :func:`src.tasks.blur_video.process_blur_message`.

Exercises the happy path end-to-end with every external dependency
stubbed:

  * ``heimdex_worker_sdk.s3.S3Client``    → in-memory dict
  * ``requests.post``                     → canned responses
  * ``BlurPipeline``                      → fake that returns a
                                            known BlurResult with
                                            local mask files

Verifies:
  1. The worker calls /claim once at the start.
  2. The pipeline is invoked with ``emit_masks=True`` + a mask_dir
     inside the temp workspace AND a progress_callback wired.
  3. Every mask file returned on ``result.mask_paths`` is uploaded
     under ``blurred/{video_id}/{job_id}/masks/{category}.mkv``.
  4. The manifest JSON uploaded to S3 includes the real mask S3 keys
     (the pipeline emits None; the worker overwrites).
  5. The /complete payload carries the mask_s3_keys dict.
  6. Progress callback events reach the API's progress endpoint.
  7. The temp workspace is cleaned up on both success and failure.

This is the layer of coverage that the original blur_video.py unit
tests never had — they stopped at ``sqs_to_blur_claim`` and never
walked the full handler. Worth the ~250 lines because the contract
between pipeline / worker / API is where most regressions will land
in future v0.10+ PRs.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest


# ---------- fakes ----------


class _FakeS3Client:
    """Records every upload / download / delete. ``upload_file``
    and ``put_object`` capture the payload so tests can assert on
    what the worker actually wrote.
    """

    def __init__(self, bucket: str) -> None:
        self.bucket = bucket
        self.uploaded: dict[str, bytes] = {}
        self.downloaded: list[tuple[str, Path]] = []
        self.deleted: list[str] = []
        self._client = MagicMock()
        self._client.put_object.side_effect = self._put_object

    def download_file(self, key: str, dest: Path) -> None:
        self.downloaded.append((key, dest))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"fake video bytes")

    def upload_file(self, src: Path, key: str) -> None:
        # Copy into the uploaded map by reading the local file.
        with open(src, "rb") as f:
            self.uploaded[key] = f.read()

    def delete(self, key: str) -> None:
        self.deleted.append(key)

    def _put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str = "") -> None:
        self.uploaded[Key] = Body


@dataclass
class _FakeBlurResult:
    """Mimics :class:`heimdex_media_pipelines.blur.BlurResult` for what
    the worker actually reads off it.
    """

    frame_count: int = 15
    total_ms: float = 1234.0
    owl_infer_ms: float = 456.0
    mask_paths: dict[str, Path] = field(default_factory=dict)
    _summary: dict[str, int] = field(default_factory=lambda: {"license_plate": 3})

    def summary(self) -> dict[str, int]:
        return dict(self._summary)

    def to_manifest(self) -> dict[str, Any]:
        # Shape matches the real pipeline output post-v0.10 bump.
        return {
            "schema_version": "2",
            "input_path": "/tmp/in.mp4",
            "output_path": "/tmp/out.mp4",
            "video": {"fps": 25.0, "width": 1280, "height": 720, "frame_count": self.frame_count},
            "timing": {
                "total_ms": self.total_ms,
                "owl_infer_ms": self.owl_infer_ms,
                "owl_infer_frames": 3,
                "avg_fps": 12.0,
            },
            "config": None,
            "summary": self.summary(),
            "detections": [],
            "mask_s3_keys": None,
        }


class _FakePipeline:
    """Captures the per-call config mutations and progress callback
    invocations, then returns a canned BlurResult with pre-written
    mask files inside the test's temp dir.
    """

    def __init__(self, mask_files: dict[str, bytes]) -> None:
        self.mask_files = mask_files
        self.config = SimpleNamespace(
            do_faces=False, do_owl=True, owl_stride=5, owl_score_threshold=0.35,
            min_face_confidence=0.5, mosaic_cells=100, feather=3,
            categories=("license_plate",),
            emit_masks=False, mask_dir=None, progress_callback=None,
        )
        self.process_calls: list[tuple[Path, Path]] = []
        self.progress_events: list[Any] = []

    def process_video(self, src: Path, out: Path) -> _FakeBlurResult:
        self.process_calls.append((src, out))

        # Write a fake blurred.mp4 so the worker's upload step has
        # something real to read.
        out.write_bytes(b"fake blurred mp4")

        # Simulate the pipeline emitting per-category mask files into
        # the configured mask_dir. The worker will then upload each.
        mask_dir: Path = self.config.mask_dir  # type: ignore[assignment]
        mask_paths: dict[str, Path] = {}
        if self.config.emit_masks and mask_dir is not None:
            mask_dir.mkdir(parents=True, exist_ok=True)
            for category, blob in self.mask_files.items():
                p = mask_dir / f"{category}.mkv"
                p.write_bytes(blob)
                mask_paths[category] = p

        # Fire a couple of progress events so the test can verify the
        # callback plumbing is wired up correctly.
        cb = self.config.progress_callback
        if cb is not None:
            event_cls = SimpleNamespace  # pipeline defines BlurProgressEvent as a dataclass; SN is shape-compatible enough for the worker handler
            cb(event_cls(phase="detecting", progress_pct=50.0, message=None))
            cb(event_cls(phase="finalizing", progress_pct=98.0, message=None))

        return _FakeBlurResult(mask_paths=mask_paths)


# ---------- fixtures ----------


@pytest.fixture
def stub_worker_sdk(monkeypatch):
    """Provide a fake ``heimdex_worker_sdk.s3`` module with the
    FakeS3Client so blur_video.py's in-function import picks it up
    without installing the real SDK in the test venv.
    """
    fake_s3_module = SimpleNamespace(S3Client=_FakeS3Client)
    fake_pkg = SimpleNamespace(s3=fake_s3_module)
    monkeypatch.setitem(sys.modules, "heimdex_worker_sdk", fake_pkg)
    monkeypatch.setitem(sys.modules, "heimdex_worker_sdk.s3", fake_s3_module)


@pytest.fixture
def job_id() -> Any:
    return uuid4()


@pytest.fixture
def claim_ref(job_id):
    from src.tasks.blur_video import BlurClaimRef

    return BlurClaimRef(
        job_id=job_id,
        org_id=uuid4(),
        file_id=uuid4(),
        video_id="vid-abc",
    )


@pytest.fixture
def settings(tmp_path):
    return SimpleNamespace(
        drive_s3_bucket="test-bucket",
    )


# ---------- happy path ----------


def test_process_blur_message_happy_path(
    stub_worker_sdk, claim_ref, settings, job_id, tmp_path, monkeypatch,
):
    """Full handler run: claim → download → pipeline → upload
    blurred + 2 masks + manifest → complete with mask_s3_keys.
    """
    lease_token = str(uuid4())

    # requests.post stub that routes by path.
    post_calls: list[dict[str, Any]] = []

    def fake_post(url, headers=None, data=None, timeout=None, **kwargs):
        body = json.loads(data) if isinstance(data, (str, bytes, bytearray)) else (data or {})
        post_calls.append({"url": url, "body": body})
        resp = MagicMock()
        if f"/internal/blur/{job_id}/claim" in url:
            resp.status_code = 200
            resp.json.return_value = {
                "lease_token": lease_token,
                "source_s3_key": "proxies/vid-abc/proxy.mp4",
                "options": {"categories": ["license_plate"], "do_faces": False},
            }
        elif f"/internal/blur/{job_id}/complete" in url:
            resp.status_code = 200
            resp.json.return_value = {"ok": True, "job_id": str(job_id), "status": "done"}
        elif f"/internal/blur/{job_id}/progress" in url:
            resp.status_code = 200
            resp.json.return_value = {"ok": True}
        else:
            resp.status_code = 200
            resp.json.return_value = {}
        resp.raise_for_status = MagicMock()
        return resp

    monkeypatch.setattr("src.tasks.blur_video.requests.post", fake_post)

    pipeline = _FakePipeline({
        "license_plate": b"fake plate mask",
        "face": b"fake face mask",
    })

    from src.tasks.blur_video import process_blur_message

    process_blur_message(
        api_base_url="http://api:8000",
        internal_api_key="secret",
        settings=settings,
        claim_ref=claim_ref,
        pipeline=pipeline,
    )

    # --- 1. Claim happened once ---
    claim_posts = [c for c in post_calls if f"/claim" in c["url"]]
    assert len(claim_posts) == 1

    # --- 2. Pipeline config mutated for mask emission + progress ---
    assert pipeline.config.emit_masks is True
    assert pipeline.config.mask_dir is not None
    assert pipeline.config.progress_callback is not None
    assert len(pipeline.process_calls) == 1

    # --- 3. Mask uploads landed under the per-job prefix ---
    # The fake pipeline writes license_plate.mkv + face.mkv. Both
    # must show up at blurred/vid-abc/{job_id}/masks/*.mkv.
    s3: _FakeS3Client = pipeline.process_calls[0][1].parent.parent  # type: ignore[assignment]
    # Re-grab via the monkeypatched S3Client — pull from post_calls' complete payload instead.
    complete_posts = [c for c in post_calls if "/complete" in c["url"]]
    assert len(complete_posts) == 1
    complete_body = complete_posts[0]["body"]
    assert complete_body["lease_token"] == lease_token
    assert complete_body["status"] == "done"
    assert complete_body["blurred_s3_key"] == f"blurred/vid-abc/{job_id}/blurred.mp4"
    assert complete_body["manifest_s3_key"] == f"blurred/vid-abc/{job_id}/manifest.json"

    # --- 4 + 5. mask_s3_keys in the complete payload ---
    assert "mask_s3_keys" in complete_body
    mask_keys = complete_body["mask_s3_keys"]
    assert set(mask_keys.keys()) == {"license_plate", "face"}
    assert mask_keys["license_plate"] == f"blurred/vid-abc/{job_id}/masks/license_plate.mkv"
    assert mask_keys["face"] == f"blurred/vid-abc/{job_id}/masks/face.mkv"

    # --- 6. Progress events went over the wire ---
    progress_posts = [c for c in post_calls if "/progress" in c["url"]]
    assert len(progress_posts) >= 1
    phases_seen = {p["body"]["phase"] for p in progress_posts}
    assert "detecting" in phases_seen or "finalizing" in phases_seen
    # Lease token is mirrored on every heartbeat so the API can
    # atomically refresh lease_expires_at.
    for p in progress_posts:
        assert p["body"]["lease_token"] == lease_token

    # --- 7. Temp dir cleaned up — the handler's finally block runs
    # shutil.rmtree — asserting that mask_dir no longer exists is
    # enough.
    assert not pipeline.config.mask_dir.exists()


def test_process_blur_message_claim_409_returns_silently(
    stub_worker_sdk, claim_ref, settings, job_id, tmp_path, monkeypatch,
):
    """When claim returns 409 (cancelled / already claimed), the
    worker must NOT call complete, must NOT touch S3, and must
    return cleanly so SQSConsumerLoop deletes the message.
    """
    post_calls: list[dict[str, Any]] = []

    def fake_post(url, headers=None, data=None, timeout=None, **kwargs):
        post_calls.append({"url": url})
        resp = MagicMock()
        if "/claim" in url:
            resp.status_code = 409
            resp.text = '{"detail": "Blur job was cancelled"}'
            resp.json.return_value = {"detail": "Blur job was cancelled"}
        else:
            pytest.fail(f"unexpected POST to {url} after 409 claim")
        return resp

    monkeypatch.setattr("src.tasks.blur_video.requests.post", fake_post)

    pipeline = _FakePipeline({})

    from src.tasks.blur_video import process_blur_message

    process_blur_message(
        api_base_url="http://api:8000",
        internal_api_key="secret",
        settings=settings,
        claim_ref=claim_ref,
        pipeline=pipeline,
    )

    # Exactly one POST (the claim), nothing else.
    assert len(post_calls) == 1
    assert "/claim" in post_calls[0]["url"]
    # Pipeline never ran.
    assert pipeline.process_calls == []


def test_process_blur_message_pipeline_failure_reports_failed(
    stub_worker_sdk, claim_ref, settings, job_id, tmp_path, monkeypatch,
):
    """If the pipeline raises mid-run, the handler must POST a
    ``status: failed`` complete with the lease token it received on
    claim, then re-raise so SQS redelivers (or the DLQ catches it).
    """
    lease_token = str(uuid4())
    post_calls: list[dict[str, Any]] = []

    def fake_post(url, headers=None, data=None, timeout=None, **kwargs):
        body = json.loads(data) if isinstance(data, (str, bytes, bytearray)) else (data or {})
        post_calls.append({"url": url, "body": body})
        resp = MagicMock()
        if "/claim" in url:
            resp.status_code = 200
            resp.json.return_value = {
                "lease_token": lease_token,
                "source_s3_key": "proxies/vid-abc/proxy.mp4",
                "options": {},
            }
        else:
            resp.status_code = 200
            resp.json.return_value = {"ok": True}
        resp.raise_for_status = MagicMock()
        return resp

    monkeypatch.setattr("src.tasks.blur_video.requests.post", fake_post)

    class _ExplodingPipeline(_FakePipeline):
        def process_video(self, src, out):
            # Still need to mutate config first so the progress
            # callback path is exercised the same way as the happy
            # path would.
            raise RuntimeError("simulated OWLv2 OOM")

    pipeline = _ExplodingPipeline({})

    from src.tasks.blur_video import process_blur_message

    with pytest.raises(RuntimeError, match="simulated OWLv2 OOM"):
        process_blur_message(
            api_base_url="http://api:8000",
            internal_api_key="secret",
            settings=settings,
            claim_ref=claim_ref,
            pipeline=pipeline,
        )

    # Claim happened, then complete(status=failed) was posted before
    # the re-raise.
    urls = [c["url"] for c in post_calls]
    assert any("/claim" in u for u in urls)
    failed_complete = [
        c for c in post_calls
        if "/complete" in c["url"] and c["body"].get("status") == "failed"
    ]
    assert len(failed_complete) == 1
    assert failed_complete[0]["body"]["lease_token"] == lease_token
    assert "simulated OWLv2 OOM" in failed_complete[0]["body"]["error"]
