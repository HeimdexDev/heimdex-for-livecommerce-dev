import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from heimdex_media_contracts.shorts.schemas import ShortsCandidate

from app.dependencies import get_video_service
from app.modules.auth import get_current_user
from app.modules.tenancy import OrgContext, get_current_org
from app.modules.videos.router import router as videos_router
from app.modules.videos.schemas import ShortsCandidateResponse, ShortsPlanResponse
from app.modules.videos.service import VideoService


def _scene(
    scene_id: str,
    *,
    start_ms: int,
    end_ms: int,
    transcript_raw: str = "",
    transcript_char_count: int = 0,
    keyword_tags: list[str] | None = None,
    product_tags: list[str] | None = None,
    people_cluster_ids: list[str] | None = None,
) -> dict[str, object]:
    return {
        "scene_id": scene_id,
        "start_ms": start_ms,
        "end_ms": end_ms,
        "transcript_raw": transcript_raw,
        "transcript_char_count": transcript_char_count,
        "keyword_tags": keyword_tags or [],
        "product_tags": product_tags or [],
        "product_entities": [],
        "speech_segment_count": 1,
        "people_cluster_ids": people_cluster_ids or [],
        "ingest_time": "2026-02-10T00:00:00Z",
        "keyframe_timestamp_ms": start_ms,
    }


def _build_service() -> tuple[VideoService, MagicMock]:
    mock_scene_client = MagicMock()
    mock_scene_client.get_video_scenes = AsyncMock()
    mock_db_session = AsyncMock()
    return VideoService(mock_db_session, mock_scene_client), mock_scene_client


def test_generate_shorts_plan_returns_scored_candidates():
    service, mock_scene_client = _build_service()
    mock_scene_client.get_video_scenes.side_effect = [
        {
            "scenes": [
                _scene(
                    "vid-1_scene_000",
                    start_ms=0,
                    end_ms=45_000,
                    transcript_raw="great product with coupon",
                    transcript_char_count=140,
                    keyword_tags=["cta", "benefit"],
                    product_tags=["skincare"],
                    people_cluster_ids=["p1"],
                )
            ],
            "total": 2,
        },
        {
            "scenes": [
                _scene(
                    "vid-1_scene_001",
                    start_ms=45_000,
                    end_ms=90_000,
                    transcript_raw="price drop now",
                    transcript_char_count=110,
                    keyword_tags=["price"],
                    product_tags=["serum"],
                )
            ],
            "total": 2,
        },
    ]

    result = asyncio.run(service.generate_shorts_plan(uuid4(), "vid-1"))

    assert result.video_id == "vid-1"
    assert result.total_scenes == 2
    assert result.eligible_scenes == 2
    assert len(result.candidates) == 2
    assert result.candidates[0].candidate_id.startswith("vid-1_shorts_")
    assert result.candidates[0].scene_ids


def test_generate_shorts_plan_empty_video():
    service, mock_scene_client = _build_service()
    mock_scene_client.get_video_scenes.return_value = {"scenes": [], "total": 0}

    result = asyncio.run(service.generate_shorts_plan(uuid4(), "vid-empty"))

    assert result.total_scenes == 0
    assert result.eligible_scenes == 0
    assert result.candidates == []


def test_generate_shorts_plan_all_outside_duration_bounds():
    service, mock_scene_client = _build_service()
    mock_scene_client.get_video_scenes.return_value = {
        "scenes": [
            _scene("vid-2_scene_000", start_ms=0, end_ms=4_000),
            _scene("vid-2_scene_001", start_ms=5_000, end_ms=140_000),
        ],
        "total": 2,
    }

    result = asyncio.run(service.generate_shorts_plan(uuid4(), "vid-2"))

    assert result.total_scenes == 2
    assert result.eligible_scenes == 0
    assert result.candidates == []


def test_generate_shorts_plan_respects_target_count():
    service, mock_scene_client = _build_service()
    mock_scene_client.get_video_scenes.return_value = {
        "scenes": [
            _scene(f"vid-3_scene_{i:03d}", start_ms=i * 50_000, end_ms=(i * 50_000) + 40_000)
            for i in range(5)
        ],
        "total": 5,
    }

    result = asyncio.run(service.generate_shorts_plan(uuid4(), "vid-3", target_count=2))

    assert len(result.candidates) == 2


def test_generate_shorts_plan_passes_custom_weights():
    service, mock_scene_client = _build_service()
    mock_scene_client.get_video_scenes.return_value = {
        "scenes": [_scene("vid-4_scene_000", start_ms=0, end_ms=40_000)],
        "total": 1,
    }
    weights = {
        "keyword_density": 1.0,
        "face_presence": 0.0,
        "transcript_richness": 0.0,
        "tag_diversity": 0.0,
        "duration_fitness": 0.0,
    }

    with patch("app.modules.videos.service.select_shorts_candidates") as mock_select:
        mock_select.return_value = [
            ShortsCandidate(
                candidate_id="vid-4_shorts_000",
                video_id="vid-4",
                scene_ids=["vid-4_scene_000"],
                start_ms=0,
                end_ms=40_000,
                score=0.9,
            )
        ]

        result = asyncio.run(
            service.generate_shorts_plan(
                uuid4(),
                "vid-4",
                target_count=1,
                min_duration_ms=30_000,
                max_duration_ms=60_000,
                weights=weights,
            )
        )

    assert len(result.candidates) == 1
    assert mock_select.call_args.kwargs["weights"] == weights


def test_endpoint_returns_shorts_plan():
    app = FastAPI()
    app.include_router(videos_router, prefix="/api")

    org_id = uuid4()
    mock_service = MagicMock()
    mock_service.generate_shorts_plan = AsyncMock(
        return_value=ShortsPlanResponse(
            video_id="vid-endpoint",
            video_title=None,
            total_scenes=1,
            eligible_scenes=1,
            candidates=[
                ShortsCandidateResponse(
                    candidate_id="vid-endpoint_shorts_000",
                    video_id="vid-endpoint",
                    scene_ids=["vid-endpoint_scene_000"],
                    start_ms=0,
                    end_ms=45_000,
                    score=0.7,
                )
            ],
        )
    )

    async def _mock_get_current_org() -> OrgContext:
        return OrgContext(org_id=org_id, org_slug="testorg")

    async def _mock_get_current_user() -> SimpleNamespace:
        return SimpleNamespace(id=uuid4())

    async def _mock_get_video_service() -> MagicMock:
        return mock_service

    app.dependency_overrides[get_current_org] = _mock_get_current_org
    app.dependency_overrides[get_current_user] = _mock_get_current_user
    app.dependency_overrides[get_video_service] = _mock_get_video_service

    with TestClient(app) as client:
        response = client.post(
            "/api/videos/vid-endpoint/shorts/plan",
            json={
                "target_count": 5,
                "min_duration_ms": 20_000,
                "max_duration_ms": 60_000,
                "weights": {"keyword_density": 0.5},
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["video_id"] == "vid-endpoint"
    assert payload["total_scenes"] == 1
    assert payload["candidates"][0]["candidate_id"] == "vid-endpoint_shorts_000"
    mock_service.generate_shorts_plan.assert_awaited_once_with(
        org_id,
        "vid-endpoint",
        target_count=5,
        min_duration_ms=20_000,
        max_duration_ms=60_000,
        weights={"keyword_density": 0.5},
    )
