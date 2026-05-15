"""Tests for enrichment SQS publishing after scene reprocess completion.

Verifies that update_reprocess_status publishes v1 (STT, OCR, face) and
v2 (caption, visual-embed) enrichment SQS jobs when status transitions
to 'completed', mirroring the Drive and YouTube processing handlers.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


ORG_ID = uuid4()
FILE_UUID = uuid4()
VIDEO_ID = "gd_abc123def456"
JOB_ID = uuid4()
KEYFRAME_PREFIX = f"{ORG_ID}/drive/keyframes/{VIDEO_ID}/"
AUDIO_KEY = f"{ORG_ID}/drive/audio/{VIDEO_ID}/audio.wav"


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.update_status = AsyncMock()
    return repo


@pytest.fixture
def mock_db():
    return AsyncMock()


class TestReprocessEnrichmentPublishing:

    @pytest.mark.asyncio
    async def test_completed_publishes_v1_enrichment(self, mock_repo, mock_db):
        with patch("app.modules.videos.internal_router.publish_enrichment_jobs") as mock_v1, \
             patch("app.modules.videos.internal_router.publish_scene_enrichment_jobs"), \
             patch("app.modules.videos.internal_router._resolve_file_id", new_callable=AsyncMock, return_value=FILE_UUID):

            from app.modules.videos.internal_router import update_reprocess_status

            result = await update_reprocess_status(
                video_id=VIDEO_ID,
                job_id=str(JOB_ID),
                status_value="completed",
                scene_count=10,
                error=None,
                org_id=str(ORG_ID),
                keyframe_s3_prefix=KEYFRAME_PREFIX,
                audio_s3_key=AUDIO_KEY,
                db=mock_db,
                repo=mock_repo,
            )

            assert result == {"status": "ok"}
            mock_v1.assert_called_once_with(
                file_id=FILE_UUID,
                org_id=ORG_ID,
                video_id=VIDEO_ID,
                keyframe_s3_prefix=KEYFRAME_PREFIX,
                audio_s3_key=AUDIO_KEY,
            )

    @pytest.mark.asyncio
    async def test_completed_publishes_v2_scene_enrichment(self, mock_repo, mock_db):
        with patch("app.modules.videos.internal_router.publish_enrichment_jobs"), \
             patch("app.modules.videos.internal_router._publish_scene_jobs_in_background", new_callable=AsyncMock) as mock_bg, \
             patch("app.modules.videos.internal_router._resolve_file_id", new_callable=AsyncMock, return_value=FILE_UUID), \
             patch("asyncio.create_task") as mock_task:

            from app.modules.videos.internal_router import update_reprocess_status

            await update_reprocess_status(
                video_id=VIDEO_ID,
                job_id=str(JOB_ID),
                status_value="completed",
                scene_count=3,
                error=None,
                org_id=str(ORG_ID),
                keyframe_s3_prefix=KEYFRAME_PREFIX,
                audio_s3_key=AUDIO_KEY,
                db=mock_db,
                repo=mock_repo,
            )

            mock_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_failed_does_not_publish_enrichment(self, mock_repo, mock_db):
        with patch("app.modules.videos.internal_router.publish_enrichment_jobs") as mock_v1, \
             patch("app.modules.videos.internal_router.publish_scene_enrichment_jobs") as mock_v2:

            from app.modules.videos.internal_router import update_reprocess_status

            await update_reprocess_status(
                video_id=VIDEO_ID,
                job_id=str(JOB_ID),
                status_value="failed",
                scene_count=None,
                error="some error",
                org_id=str(ORG_ID),
                keyframe_s3_prefix=KEYFRAME_PREFIX,
                audio_s3_key=AUDIO_KEY,
                db=mock_db,
                repo=mock_repo,
            )

            mock_v1.assert_not_called()
            mock_v2.assert_not_called()

    @pytest.mark.asyncio
    async def test_processing_does_not_publish_enrichment(self, mock_repo, mock_db):
        with patch("app.modules.videos.internal_router.publish_enrichment_jobs") as mock_v1, \
             patch("app.modules.videos.internal_router.publish_scene_enrichment_jobs") as mock_v2:

            from app.modules.videos.internal_router import update_reprocess_status

            await update_reprocess_status(
                video_id=VIDEO_ID,
                job_id=str(JOB_ID),
                status_value="processing",
                scene_count=None,
                error=None,
                org_id=None,
                keyframe_s3_prefix=None,
                audio_s3_key=None,
                db=mock_db,
                repo=mock_repo,
            )

            mock_v1.assert_not_called()
            mock_v2.assert_not_called()

    @pytest.mark.asyncio
    async def test_completed_without_org_id_skips_enrichment(self, mock_repo, mock_db):
        with patch("app.modules.videos.internal_router.publish_enrichment_jobs") as mock_v1:

            from app.modules.videos.internal_router import update_reprocess_status

            await update_reprocess_status(
                video_id=VIDEO_ID,
                job_id=str(JOB_ID),
                status_value="completed",
                scene_count=10,
                error=None,
                org_id=None,
                keyframe_s3_prefix=KEYFRAME_PREFIX,
                audio_s3_key=AUDIO_KEY,
                db=mock_db,
                repo=mock_repo,
            )

            mock_v1.assert_not_called()

    @pytest.mark.asyncio
    async def test_completed_without_keyframe_prefix_skips_enrichment(self, mock_repo, mock_db):
        with patch("app.modules.videos.internal_router.publish_enrichment_jobs") as mock_v1:

            from app.modules.videos.internal_router import update_reprocess_status

            await update_reprocess_status(
                video_id=VIDEO_ID,
                job_id=str(JOB_ID),
                status_value="completed",
                scene_count=10,
                error=None,
                org_id=str(ORG_ID),
                keyframe_s3_prefix=None,
                audio_s3_key=AUDIO_KEY,
                db=mock_db,
                repo=mock_repo,
            )

            mock_v1.assert_not_called()

    @pytest.mark.asyncio
    async def test_completed_zero_scenes_skips_enrichment(self, mock_repo, mock_db):
        with patch("app.modules.videos.internal_router.publish_enrichment_jobs") as mock_v1:

            from app.modules.videos.internal_router import update_reprocess_status

            await update_reprocess_status(
                video_id=VIDEO_ID,
                job_id=str(JOB_ID),
                status_value="completed",
                scene_count=0,
                error=None,
                org_id=str(ORG_ID),
                keyframe_s3_prefix=KEYFRAME_PREFIX,
                audio_s3_key=AUDIO_KEY,
                db=mock_db,
                repo=mock_repo,
            )

            mock_v1.assert_not_called()

    @pytest.mark.asyncio
    async def test_file_id_not_found_skips_enrichment(self, mock_repo, mock_db):
        with patch("app.modules.videos.internal_router.publish_enrichment_jobs") as mock_v1, \
             patch("app.modules.videos.internal_router._resolve_file_id", new_callable=AsyncMock, return_value=None):

            from app.modules.videos.internal_router import update_reprocess_status

            await update_reprocess_status(
                video_id=VIDEO_ID,
                job_id=str(JOB_ID),
                status_value="completed",
                scene_count=10,
                error=None,
                org_id=str(ORG_ID),
                keyframe_s3_prefix=KEYFRAME_PREFIX,
                audio_s3_key=AUDIO_KEY,
                db=mock_db,
                repo=mock_repo,
            )

            mock_v1.assert_not_called()


class TestResolveFileId:

    @pytest.mark.asyncio
    async def test_gd_video_resolves_drive_file(self, mock_db):
        drive_file = MagicMock()
        drive_file.id = FILE_UUID

        with patch("app.modules.drive.repository.DriveFileRepository") as MockRepo:
            repo_instance = MagicMock()
            repo_instance.get_by_video_id = AsyncMock(return_value=drive_file)
            MockRepo.return_value = repo_instance

            from app.modules.videos.internal_router import _resolve_file_id
            result = await _resolve_file_id(mock_db, "gd_abc123", ORG_ID)
            assert result == FILE_UUID

    @pytest.mark.asyncio
    async def test_yt_video_resolves_youtube_video(self, mock_db):
        yt_video = MagicMock()
        yt_video.id = FILE_UUID

        with patch("app.modules.youtube.repository.YouTubeVideoRepository") as MockRepo:
            repo_instance = MagicMock()
            repo_instance.get_by_video_id = AsyncMock(return_value=yt_video)
            MockRepo.return_value = repo_instance

            from app.modules.videos.internal_router import _resolve_file_id
            result = await _resolve_file_id(mock_db, "yt_xyz789", ORG_ID)
            assert result == FILE_UUID

    @pytest.mark.asyncio
    async def test_unknown_prefix_returns_none(self, mock_db):
        from app.modules.videos.internal_router import _resolve_file_id
        result = await _resolve_file_id(mock_db, "unknown_abc", ORG_ID)
        assert result is None

    @pytest.mark.asyncio
    async def test_gd_video_not_found_returns_none(self, mock_db):
        with patch("app.modules.drive.repository.DriveFileRepository") as MockRepo:
            repo_instance = MagicMock()
            repo_instance.get_by_video_id = AsyncMock(return_value=None)
            MockRepo.return_value = repo_instance

            from app.modules.videos.internal_router import _resolve_file_id
            result = await _resolve_file_id(mock_db, "gd_notfound", ORG_ID)
            assert result is None
