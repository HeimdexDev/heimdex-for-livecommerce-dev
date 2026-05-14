"""Tests for ShortsRenderService."""

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.modules.shorts_render.schemas import RenderJobCreate
from app.modules.shorts_render.service import ShortsRenderService


def _make_composition(
    scene_id: str = "scene_001",
    video_id: str = "vid-1",
    start_ms: int = 1000,
    end_ms: int = 5000,
) -> dict:
    return {
        "video_id": video_id,
        "composition": {
            "scene_clips": [
                {
                    "scene_id": scene_id,
                    "video_id": video_id,
                    "start_ms": start_ms,
                    "end_ms": end_ms,
                    "timeline_start_ms": 0,
                }
            ],
        },
    }


def _make_job(
    *,
    status: str = "queued",
    output_s3_key: str | None = None,
    job_id=None,
    org_id=None,
):
    job = SimpleNamespace(
        id=job_id or uuid4(),
        org_id=org_id or uuid4(),
        user_id=uuid4(),
        video_id="vid-1",
        title="Test",
        status=status,
        created_at=datetime.now(timezone.utc),
        completed_at=None,
        render_time_ms=None,
        output_duration_ms=None,
        output_size_bytes=None,
        output_s3_key=output_s3_key,
        error=None,
        input_spec=_make_composition()["composition"],
        replaced_by_render_job_id=None,
        refined_from_render_job_id=None,
        refinement_source=None,
        summary=None,
        summary_prompt_version=None,
        summary_generated_at=None,
    )
    return job


def _build_service():
    repo = MagicMock()
    repo.create = AsyncMock()
    repo.update_status = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.list_by_user = AsyncMock()
    repo.walk_to_leaf = AsyncMock()
    repo.delete = AsyncMock()
    repo.find_recent_duplicate = AsyncMock(return_value=None)
    repo.session = MagicMock()
    repo.session.commit = AsyncMock()

    scene_search = MagicMock()
    scene_search.mget_scenes = AsyncMock()

    return ShortsRenderService(repo, scene_search), repo, scene_search


# --- Test 16: create_render_job calls repo.create + sqs publish ---


def test_create_render_job_calls_repo_and_sqs():
    service, repo, scene_search = _build_service()
    org_id, user_id = uuid4(), uuid4()
    job = _make_job(org_id=org_id)
    repo.create.return_value = job

    scene_search.mget_scenes.return_value = {
        f"{org_id}:scene_001": {"start_ms": 0, "end_ms": 10000},
    }

    payload = RenderJobCreate(**_make_composition())

    with patch("app.sqs_producer.publish_shorts_render_job") as mock_sqs:
        result = asyncio.run(service.create_render_job(org_id, user_id, payload))

    repo.create.assert_awaited_once()
    mock_sqs.assert_called_once()
    assert result.id == job.id


# --- Test 17: SQS failure marks render failed ---


def test_create_render_job_sqs_failure_marks_job_failed():
    service, repo, scene_search = _build_service()
    org_id, user_id = uuid4(), uuid4()
    job = _make_job(org_id=org_id)
    repo.create.return_value = job

    scene_search.mget_scenes.return_value = {
        f"{org_id}:scene_001": {"start_ms": 0, "end_ms": 10000},
    }

    payload = RenderJobCreate(**_make_composition())

    with patch(
        "app.sqs_producer.publish_shorts_render_job",
        side_effect=RuntimeError("SQS down"),
    ):
        result = asyncio.run(service.create_render_job(org_id, user_id, payload))

    assert result.id == job.id
    assert result.status == "failed"
    assert result.error == "Failed to enqueue render job"
    repo.update_status.assert_awaited_once()


# --- Test 18: get_render_job completed → download_url populated ---


def test_get_render_job_completed_has_download_url():
    service, repo, _ = _build_service()
    org_id = uuid4()
    user_id = uuid4()
    job_id = uuid4()
    job = _make_job(status="completed", output_s3_key="renders/out.mp4", job_id=job_id, org_id=org_id)
    repo.get_by_id.return_value = job

    with patch("app.storage.s3.S3Client") as MockS3:
        mock_s3_instance = MagicMock()
        mock_s3_instance.generate_presigned_url_async = AsyncMock(
            return_value="https://signed.example/render.mp4",
        )
        MockS3.return_value = mock_s3_instance

        result = asyncio.run(service.get_render_job(org_id, user_id, job_id))

    assert result.download_url == "https://signed.example/render.mp4"


# --- get_render_job: refinement chain resolution ---


def test_get_render_job_intermediate_resolves_to_leaf():
    """When called with an intermediate render's id, the response keeps the
    requested row's metadata (so the FE can see 'you asked for X') but
    download_url + effective_render_job_id point at the chain's leaf."""
    service, repo, _ = _build_service()
    org_id = uuid4()
    user_id = uuid4()

    leaf = _make_job(
        status="completed",
        output_s3_key="renders/leaf.mp4",
        org_id=org_id,
    )
    leaf.refinement_source = "manual_edit"
    intermediate = _make_job(
        status="completed",
        output_s3_key="renders/intermediate.mp4",
        org_id=org_id,
    )
    intermediate.replaced_by_render_job_id = leaf.id
    intermediate.refinement_source = "whisper"

    repo.get_by_id.return_value = intermediate
    repo.walk_to_leaf.return_value = leaf

    with patch("app.storage.s3.S3Client") as MockS3:
        s3 = MagicMock()
        s3.generate_presigned_url_async = AsyncMock(
            return_value="https://signed.example/leaf.mp4",
        )
        MockS3.return_value = s3

        result = asyncio.run(
            service.get_render_job(org_id, user_id, intermediate.id),
        )

    # Identity preserved: caller asked for the intermediate.
    assert result.id == intermediate.id
    # But download + effective pointer steer to the leaf.
    assert result.download_url == "https://signed.example/leaf.mp4"
    assert result.effective_render_job_id == leaf.id
    # S3 was presigned against the leaf's key, not the intermediate's.
    s3.generate_presigned_url_async.assert_awaited_once()
    presigned_key = s3.generate_presigned_url_async.await_args.args[0]
    assert presigned_key == "renders/leaf.mp4"


def test_get_render_job_leaf_skips_chain_walk():
    """The common path: a row that is already its own leaf must NOT
    call walk_to_leaf. Saves a query per request on the hot path."""
    service, repo, _ = _build_service()
    org_id = uuid4()
    user_id = uuid4()

    leaf = _make_job(
        status="completed",
        output_s3_key="renders/leaf.mp4",
        org_id=org_id,
    )
    # replaced_by_render_job_id is None by default in _make_job.

    repo.get_by_id.return_value = leaf

    with patch("app.storage.s3.S3Client") as MockS3:
        s3 = MagicMock()
        s3.generate_presigned_url_async = AsyncMock(
            return_value="https://signed.example/leaf.mp4",
        )
        MockS3.return_value = s3

        result = asyncio.run(service.get_render_job(org_id, user_id, leaf.id))

    assert result.download_url == "https://signed.example/leaf.mp4"
    assert result.effective_render_job_id is None
    # walk_to_leaf must not be invoked on the common "self is leaf" path.
    repo.walk_to_leaf.assert_not_awaited()


def test_get_render_job_broken_chain_falls_back_to_self():
    """If walk_to_leaf returns None (deleted leaf) or somehow returns the
    same row, the response falls back to the requested row's own MP4 —
    avoids 500-ing on dangling FK state."""
    service, repo, _ = _build_service()
    org_id = uuid4()
    user_id = uuid4()

    intermediate = _make_job(
        status="completed",
        output_s3_key="renders/intermediate.mp4",
        org_id=org_id,
    )
    intermediate.replaced_by_render_job_id = uuid4()  # dangling

    repo.get_by_id.return_value = intermediate
    repo.walk_to_leaf.return_value = None  # leaf deleted

    with patch("app.storage.s3.S3Client") as MockS3:
        s3 = MagicMock()
        s3.generate_presigned_url_async = AsyncMock(
            return_value="https://signed.example/intermediate.mp4",
        )
        MockS3.return_value = s3

        result = asyncio.run(
            service.get_render_job(org_id, user_id, intermediate.id),
        )

    assert result.download_url == "https://signed.example/intermediate.mp4"
    assert result.effective_render_job_id is None
    presigned_key = s3.generate_presigned_url_async.await_args.args[0]
    assert presigned_key == "renders/intermediate.mp4"


# --- Test 19: get_render_job not found → 404 ---


def test_get_render_job_not_found_raises_404():
    service, repo, _ = _build_service()
    repo.get_by_id.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.get_render_job(uuid4(), uuid4(), uuid4()))

    assert exc_info.value.status_code == 404


# --- Test 20: list_render_jobs → returns RenderJobListResponse ---


def test_list_render_jobs_returns_response():
    service, repo, _ = _build_service()
    jobs = [_make_job(), _make_job()]
    repo.list_by_user.return_value = (jobs, 2)

    result = asyncio.run(service.list_render_jobs(uuid4(), uuid4(), limit=20, offset=0))

    assert result.total == 2
    assert len(result.items) == 2


# --- Test 21: delete_render_job with S3 key → deletes S3 + DB ---


def test_delete_render_job_with_s3_key_deletes_both():
    service, repo, _ = _build_service()
    org_id = uuid4()
    user_id = uuid4()
    job_id = uuid4()
    job = _make_job(output_s3_key="renders/out.mp4", job_id=job_id, org_id=org_id)
    repo.get_by_id.return_value = job

    with patch("app.storage.s3.S3Client") as MockS3:
        mock_s3_instance = MagicMock()
        MockS3.return_value = mock_s3_instance

        asyncio.run(service.delete_render_job(org_id, user_id, job_id))

    mock_s3_instance.delete.assert_called_once_with("renders/out.mp4")
    repo.delete.assert_awaited_once_with(org_id, user_id, job_id)


# --- Test 22: delete_render_job without S3 key → DB only ---


def test_delete_render_job_without_s3_key_deletes_db_only():
    service, repo, _ = _build_service()
    org_id = uuid4()
    user_id = uuid4()
    job_id = uuid4()
    job = _make_job(output_s3_key=None, job_id=job_id, org_id=org_id)
    repo.get_by_id.return_value = job

    with patch("app.storage.s3.S3Client") as MockS3:
        asyncio.run(service.delete_render_job(org_id, user_id, job_id))

    MockS3.assert_not_called()
    repo.delete.assert_awaited_once_with(org_id, user_id, job_id)


# --- Test 23: delete_render_job not found → 404 ---


def test_delete_render_job_not_found_raises_404():
    service, repo, _ = _build_service()
    repo.get_by_id.return_value = None

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.delete_render_job(uuid4(), uuid4(), uuid4()))

    assert exc_info.value.status_code == 404


# --- Test 24: create_render_job clip within scene bounds → passes ---


def test_create_clip_within_bounds_passes():
    service, repo, scene_search = _build_service()
    org_id, user_id = uuid4(), uuid4()
    job = _make_job(org_id=org_id)
    repo.create.return_value = job

    scene_search.mget_scenes.return_value = {
        f"{org_id}:scene_001": {"start_ms": 0, "end_ms": 10000},
    }

    payload = RenderJobCreate(**_make_composition(start_ms=1000, end_ms=5000))

    with patch("app.sqs_producer.publish_shorts_render_job"):
        result = asyncio.run(service.create_render_job(org_id, user_id, payload))

    assert result.id == job.id


# --- Test 25: clip.start_ms < scene.start_ms → 422 ---


def test_create_clip_start_before_scene_raises_422():
    service, repo, scene_search = _build_service()
    org_id = uuid4()

    scene_search.mget_scenes.return_value = {
        f"{org_id}:scene_001": {"start_ms": 2000, "end_ms": 10000},
    }

    payload = RenderJobCreate(**_make_composition(start_ms=1000, end_ms=5000))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.create_render_job(org_id, uuid4(), payload))

    assert exc_info.value.status_code == 422
    assert "start_ms out of scene bounds" in exc_info.value.detail


# --- Test 26: clip.end_ms > scene.end_ms → 422 ---


def test_create_clip_end_after_scene_raises_422():
    service, repo, scene_search = _build_service()
    org_id = uuid4()

    scene_search.mget_scenes.return_value = {
        f"{org_id}:scene_001": {"start_ms": 0, "end_ms": 4000},
    }

    payload = RenderJobCreate(**_make_composition(start_ms=1000, end_ms=5000))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.create_render_job(org_id, uuid4(), payload))

    assert exc_info.value.status_code == 422
    assert "end_ms out of scene bounds" in exc_info.value.detail


# --- Test 27: non-existent scene_id → 422 ---


def test_create_nonexistent_scene_raises_422():
    service, repo, scene_search = _build_service()
    org_id = uuid4()

    scene_search.mget_scenes.return_value = {}  # No scenes found

    payload = RenderJobCreate(**_make_composition())

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.create_render_job(org_id, uuid4(), payload))

    assert exc_info.value.status_code == 422
    assert "not found" in exc_info.value.detail


# --- Test 28: 422 error detail includes clip index and bounds ---


def test_422_error_includes_clip_index_and_bounds():
    service, repo, scene_search = _build_service()
    org_id = uuid4()

    scene_search.mget_scenes.return_value = {
        f"{org_id}:scene_001": {"start_ms": 0, "end_ms": 3000},
    }

    payload = RenderJobCreate(**_make_composition(start_ms=1000, end_ms=5000))

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(service.create_render_job(org_id, uuid4(), payload))

    detail = exc_info.value.detail
    assert "scene_clip[0]" in detail
    assert "1000-5000" in detail
    assert "0-3000" in detail
