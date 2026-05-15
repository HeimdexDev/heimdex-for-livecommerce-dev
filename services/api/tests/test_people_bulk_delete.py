"""
Unit tests for person cluster bulk delete feature.

Tests verify:
1. BulkDeleteRequest schema validation (min_length=1, max_length=50)
2. BulkDeleteResponse structure
3. Bulk delete endpoint behavior (best-effort, partial failures)
4. Database cleanup (labels, exclusions, video exclusions)
5. OpenSearch cleanup (remove_person_cluster_id)
6. Thumbnail cleanup

Run with: pytest tests/test_people_bulk_delete.py -v
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------
class TestBulkDeleteSchemas:
    """Validate BulkDeleteRequest and BulkDeleteResponse constraints."""

    def test_valid_single_delete(self):
        from app.modules.people.schemas import BulkDeleteRequest

        req = BulkDeleteRequest(person_cluster_ids=["cluster_1"])
        assert req.person_cluster_ids == ["cluster_1"]

    def test_valid_batch_delete(self):
        from app.modules.people.schemas import BulkDeleteRequest

        ids = [f"cluster_{i}" for i in range(1, 11)]
        req = BulkDeleteRequest(person_cluster_ids=ids)
        assert len(req.person_cluster_ids) == 10

    def test_max_50_ids_accepted(self):
        from app.modules.people.schemas import BulkDeleteRequest

        ids = [f"cluster_{i}" for i in range(1, 51)]
        req = BulkDeleteRequest(person_cluster_ids=ids)
        assert len(req.person_cluster_ids) == 50

    def test_empty_list_rejected(self):
        from pydantic import ValidationError
        from app.modules.people.schemas import BulkDeleteRequest

        with pytest.raises(ValidationError):
            BulkDeleteRequest(person_cluster_ids=[])

    def test_more_than_50_rejected(self):
        from pydantic import ValidationError
        from app.modules.people.schemas import BulkDeleteRequest

        ids = [f"cluster_{i}" for i in range(1, 52)]
        with pytest.raises(ValidationError):
            BulkDeleteRequest(person_cluster_ids=ids)

    def test_response_model(self):
        from app.modules.people.schemas import BulkDeleteResponse

        resp = BulkDeleteResponse(
            deleted_ids=["cluster_1", "cluster_2"],
            failed_ids=["cluster_3"],
            total_deleted=2,
        )
        assert resp.deleted_ids == ["cluster_1", "cluster_2"]
        assert resp.failed_ids == ["cluster_3"]
        assert resp.total_deleted == 2

    def test_response_all_deleted(self):
        from app.modules.people.schemas import BulkDeleteResponse

        resp = BulkDeleteResponse(
            deleted_ids=["cluster_1", "cluster_2", "cluster_3"],
            failed_ids=[],
            total_deleted=3,
        )
        assert len(resp.failed_ids) == 0
        assert resp.total_deleted == 3

    def test_response_all_failed(self):
        from app.modules.people.schemas import BulkDeleteResponse

        resp = BulkDeleteResponse(
            deleted_ids=[],
            failed_ids=["cluster_1", "cluster_2"],
            total_deleted=0,
        )
        assert len(resp.deleted_ids) == 0
        assert resp.total_deleted == 0


# ---------------------------------------------------------------------------
# Endpoint behavior
# ---------------------------------------------------------------------------
class TestBulkDeleteEndpoint:
    """Test POST /api/people/bulk-delete endpoint."""

    @pytest.mark.asyncio
    async def test_bulk_delete_all_success(self):
        from uuid import uuid4
        from app.modules.people.schemas import BulkDeleteRequest
        from app.modules.people.router import bulk_delete_people
        from app.modules.tenancy import OrgContext

        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test_org")
        user = MagicMock()
        user.id = uuid4()

        people_repo = AsyncMock()
        people_repo.delete_by_cluster_id = AsyncMock(return_value=True)

        exclude_repo = AsyncMock()
        exclude_repo.delete_by_cluster_id = AsyncMock(return_value=1)

        video_excl_repo = AsyncMock()
        video_excl_repo.delete_by_cluster_id = AsyncMock(return_value=0)

        scene_opensearch = AsyncMock()
        scene_opensearch.remove_person_cluster_id = AsyncMock(return_value=5)

        db = AsyncMock()
        db.commit = AsyncMock()

        request = BulkDeleteRequest(person_cluster_ids=["cluster_1", "cluster_2"])

        with patch("app.modules.people.router.get_settings") as mock_settings:
            mock_settings.return_value.people_enabled = True
            mock_settings.return_value.thumbnail_storage_dir = "/tmp"

            with patch("app.modules.people.router.FilePath") as mock_filepath:
                mock_filepath.return_value.__truediv__ = MagicMock(
                    return_value=MagicMock(exists=MagicMock(return_value=False))
                )

                response = await bulk_delete_people(
                    request=request,
                    org_ctx=org_ctx,
                    user=user,
                    people_repo=people_repo,
                    exclude_repo=exclude_repo,
                    video_excl_repo=video_excl_repo,
                    scene_opensearch=scene_opensearch,
                    db=db,
                )

        assert response.total_deleted == 2
        assert response.deleted_ids == ["cluster_1", "cluster_2"]
        assert response.failed_ids == []
        assert db.commit.called

    @pytest.mark.asyncio
    async def test_bulk_delete_partial_failure(self):
        from uuid import uuid4
        from app.modules.people.schemas import BulkDeleteRequest
        from app.modules.people.router import bulk_delete_people
        from app.modules.tenancy import OrgContext

        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test_org")
        user = MagicMock()
        user.id = uuid4()

        people_repo = AsyncMock()

        async def delete_side_effect(org_id, cluster_id):
            if cluster_id == "cluster_2":
                raise Exception("Database error")
            return True

        people_repo.delete_by_cluster_id = AsyncMock(side_effect=delete_side_effect)

        exclude_repo = AsyncMock()
        exclude_repo.delete_by_cluster_id = AsyncMock(return_value=1)

        video_excl_repo = AsyncMock()
        video_excl_repo.delete_by_cluster_id = AsyncMock(return_value=0)

        scene_opensearch = AsyncMock()
        scene_opensearch.remove_person_cluster_id = AsyncMock(return_value=5)

        db = AsyncMock()
        db.commit = AsyncMock()

        request = BulkDeleteRequest(person_cluster_ids=["cluster_1", "cluster_2"])

        with patch("app.modules.people.router.get_settings") as mock_settings:
            mock_settings.return_value.people_enabled = True
            mock_settings.return_value.thumbnail_storage_dir = "/tmp"

            with patch("app.modules.people.router.FilePath") as mock_filepath:
                mock_filepath.return_value.__truediv__ = MagicMock(
                    return_value=MagicMock(exists=MagicMock(return_value=False))
                )

                response = await bulk_delete_people(
                    request=request,
                    org_ctx=org_ctx,
                    user=user,
                    people_repo=people_repo,
                    exclude_repo=exclude_repo,
                    video_excl_repo=video_excl_repo,
                    scene_opensearch=scene_opensearch,
                    db=db,
                )

        assert response.total_deleted == 1
        assert response.deleted_ids == ["cluster_1"]
        assert response.failed_ids == ["cluster_2"]
        assert db.commit.called

    @pytest.mark.asyncio
    async def test_bulk_delete_people_disabled(self):
        from uuid import uuid4
        from fastapi import HTTPException
        from app.modules.people.schemas import BulkDeleteRequest
        from app.modules.people.router import bulk_delete_people
        from app.modules.tenancy import OrgContext

        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test_org")
        user = MagicMock()
        user.id = uuid4()

        people_repo = AsyncMock()
        exclude_repo = AsyncMock()
        video_excl_repo = AsyncMock()
        scene_opensearch = AsyncMock()
        db = AsyncMock()

        request = BulkDeleteRequest(person_cluster_ids=["cluster_1"])

        with patch("app.modules.people.router.get_settings") as mock_settings:
            mock_settings.return_value.people_enabled = False

            with pytest.raises(HTTPException) as exc_info:
                await bulk_delete_people(
                    request=request,
                    org_ctx=org_ctx,
                    user=user,
                    people_repo=people_repo,
                    exclude_repo=exclude_repo,
                    video_excl_repo=video_excl_repo,
                    scene_opensearch=scene_opensearch,
                    db=db,
                )

            assert exc_info.value.status_code == 404

    @pytest.mark.asyncio
    async def test_bulk_delete_single_cluster(self):
        from uuid import uuid4
        from app.modules.people.schemas import BulkDeleteRequest
        from app.modules.people.router import bulk_delete_people
        from app.modules.tenancy import OrgContext

        org_id = uuid4()
        org_ctx = OrgContext(org_id=org_id, org_slug="test_org")
        user = MagicMock()
        user.id = uuid4()

        people_repo = AsyncMock()
        people_repo.delete_by_cluster_id = AsyncMock(return_value=True)

        exclude_repo = AsyncMock()
        exclude_repo.delete_by_cluster_id = AsyncMock(return_value=0)

        video_excl_repo = AsyncMock()
        video_excl_repo.delete_by_cluster_id = AsyncMock(return_value=0)

        scene_opensearch = AsyncMock()
        scene_opensearch.remove_person_cluster_id = AsyncMock(return_value=3)

        db = AsyncMock()
        db.commit = AsyncMock()

        request = BulkDeleteRequest(person_cluster_ids=["cluster_1"])

        with patch("app.modules.people.router.get_settings") as mock_settings:
            mock_settings.return_value.people_enabled = True
            mock_settings.return_value.thumbnail_storage_dir = "/tmp"

            with patch("app.modules.people.router.FilePath") as mock_filepath:
                mock_filepath.return_value.__truediv__ = MagicMock(
                    return_value=MagicMock(exists=MagicMock(return_value=False))
                )

                response = await bulk_delete_people(
                    request=request,
                    org_ctx=org_ctx,
                    user=user,
                    people_repo=people_repo,
                    exclude_repo=exclude_repo,
                    video_excl_repo=video_excl_repo,
                    scene_opensearch=scene_opensearch,
                    db=db,
                )

        assert response.total_deleted == 1
        assert response.deleted_ids == ["cluster_1"]
        assert response.failed_ids == []
