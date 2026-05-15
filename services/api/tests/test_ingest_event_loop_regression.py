"""Regression tests for the asyncio event-loop blocker incident on 2026-05-11.

The bug class: ``get_passage_embeddings_batch`` is sync CPU work
(``model.encode``) that takes 60-130s per batch in prod. Calling it
directly inside an ``async def`` handler freezes the entire asyncio
event loop and 504s every concurrent request — including ``/health``,
``/api/devices/``, ``/api/shorts/auto/...``. Both call sites in
``app/modules/ingest/service.py`` must wrap it in ``asyncio.to_thread``.

These tests pin the threading invariant. If a future change removes the
``to_thread`` wrapper, the test fails fast — it asserts the embedding
function ran on a thread DIFFERENT from the event-loop thread.

Self-contained on purpose: the wider ``test_internal_enrich.py`` and
``test_scene_ingest.py`` files have a fixture mismatch with the newer
``SceneOverrideRepository`` query path (AsyncMock mishandles
``result.all()``) and aren't in the CI allowlist. This file IS in the
allowlist so the regression is enforced on every PR.
"""
import threading

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from heimdex_media_contracts.ingest import IngestSceneDocument, IngestScenesRequest

from app.modules.ingest.schemas import EnrichSceneUpdate, EnrichScenesRequest
from app.modules.ingest.service import SceneIngestService


@pytest.fixture
def mock_scene_client():
    client = MagicMock()
    client.mget_scenes = AsyncMock()
    client.bulk_index_scenes = AsyncMock()
    client.bulk_partial_update_scenes = AsyncMock()
    return client


@pytest.fixture
def mock_db_session():
    return AsyncMock()


@pytest.fixture
def service(mock_db_session, mock_scene_client):
    return SceneIngestService(mock_db_session, mock_scene_client)


@pytest.mark.asyncio
async def test_enrich_runs_embedding_off_event_loop(service, mock_scene_client):
    """``get_passage_embeddings_batch`` must run via ``asyncio.to_thread``.

    Sync CPU work on the loop thread blocks every concurrent handler. The
    enrich path was a 60-130s freeze in prod, surfacing as 504s on
    unrelated endpoints.
    """
    org_id = uuid4()
    scene_id = "vid1_scene_0"
    doc_id = f"{org_id}:{scene_id}"
    request = EnrichScenesRequest(
        video_id="vid1",
        scenes=[EnrichSceneUpdate(scene_id=scene_id, transcript_raw="hello world")],
    )
    mock_scene_client.mget_scenes.return_value = {
        doc_id: {
            "scene_id": scene_id,
            "transcript_raw": "",
            "ocr_text_raw": "",
            "scene_caption": "",
        }
    }

    loop_thread_ident = threading.get_ident()
    embed_thread_ident: list[int] = []

    def _record_thread(_texts):
        embed_thread_ident.append(threading.get_ident())
        return [[0.1] * 1024]

    # Skip the SceneOverrideRepository DB round-trip — its
    # ``session.execute().all()`` path doesn't compose with bare AsyncMock
    # and isn't relevant to the threading invariant we're pinning.
    with patch(
        "app.modules.scene_overrides.repository.SceneOverrideRepository.get_overridden_fields",
        AsyncMock(return_value={}),
    ), patch(
        "app.modules.ingest.service.get_passage_embeddings_batch",
        side_effect=_record_thread,
    ):
        await service.enrich_scenes(request, org_id)

    assert embed_thread_ident, "get_passage_embeddings_batch was never called"
    assert embed_thread_ident[0] != loop_thread_ident, (
        "get_passage_embeddings_batch ran on the event-loop thread; "
        "wrap the call in asyncio.to_thread or every concurrent handler "
        "will 504 while embedding runs"
    )


@pytest.mark.asyncio
async def test_ingest_runs_embedding_off_event_loop(
    service, mock_db_session, mock_scene_client
):
    """Sibling regression for ``ingest_scenes`` — same bug class, same
    blast radius. Both call sites must stay wrapped in
    ``asyncio.to_thread``.
    """
    org_id = uuid4()
    lib_id = uuid4()
    request = IngestScenesRequest(
        video_id="vid_abc",
        video_title="Sample",
        library_id=lib_id,
        pipeline_version="1.0",
        model_version="whisper-v3",
        total_duration_ms=10000,
        scenes=[
            IngestSceneDocument(
                scene_id="vid_abc_scene_0",
                index=0,
                start_ms=0,
                end_ms=10000,
                transcript_raw="hello world",
                speech_segment_count=1,
            ),
        ],
    )

    mock_lib = MagicMock()
    mock_lib.id = lib_id
    mock_lib.org_id = org_id
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_lib
    mock_db_session.execute = AsyncMock(return_value=mock_result)

    loop_thread_ident = threading.get_ident()
    embed_thread_ident: list[int] = []

    def _record_thread(_texts):
        embed_thread_ident.append(threading.get_ident())
        return [[0.1] * 1024]

    with patch(
        "app.modules.ingest.service.get_passage_embeddings_batch",
        side_effect=_record_thread,
    ):
        await service.ingest_scenes(request, org_id)

    assert embed_thread_ident, "get_passage_embeddings_batch was never called"
    assert embed_thread_ident[0] != loop_thread_ident, (
        "get_passage_embeddings_batch ran on the event-loop thread; "
        "wrap the call in asyncio.to_thread or every concurrent handler "
        "will 504 while embedding runs"
    )
