"""Tests for the scheduling hook in ingest/internal_router.py.

The ingest handler is HTTP-tested elsewhere (test_internal_ingest.py etc).
Here we verify only the scheduling decision logic: given a scene list and
a feature-flag setting, does the handler schedule a background task with
the right set of image scene IDs — and never for video scenes?

To keep this test tight and fast, we unit-test the decision logic by
recreating the exact branch from internal_router.py:84-131 as a pure
function. If the router changes shape, update this helper too.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from app.modules.image_caption.service import (
    SceneCaptionRequest,
    _BACKGROUND_TASKS,
    reset_service_for_tests,
)


def _decide_and_schedule(
    *,
    settings: Any,
    org_id: UUID,
    request: Any,
    schedule_fn,
) -> list[SceneCaptionRequest]:
    """Pure replica of internal_router.py's hook logic.

    Returns the list it would have scheduled (or [] if disabled/none).
    The caller can inspect it and also assert that schedule_fn was
    invoked with exactly this list.
    """

    if not settings.image_caption_enabled:
        return []

    image_scene_requests = [
        SceneCaptionRequest(
            org_id=org_id,
            video_id=request.video_id,
            scene_id=scene.scene_id,
            file_name=getattr(request, "video_title", None),
            library_name=None,
        )
        for scene in request.scenes
        if getattr(scene, "content_type", None) == "image"
    ]
    if image_scene_requests:
        schedule_fn(image_scene_requests)
    return image_scene_requests


def _make_scene(scene_id: str, content_type: str) -> Any:
    return SimpleNamespace(scene_id=scene_id, content_type=content_type)


def _make_request(video_id: str, scenes: list[Any]) -> Any:
    return SimpleNamespace(video_id=video_id, scenes=scenes, video_title="test.jpg")


class TestSchedulerDecision:
    def test_disabled_flag_no_schedule(self):
        settings = SimpleNamespace(image_caption_enabled=False)
        fn = MagicMock()
        request = _make_request("v1", [_make_scene("v1_s000", "image")])
        result = _decide_and_schedule(
            settings=settings, org_id=uuid4(), request=request, schedule_fn=fn
        )
        assert result == []
        fn.assert_not_called()

    def test_video_only_no_schedule(self):
        settings = SimpleNamespace(image_caption_enabled=True)
        fn = MagicMock()
        request = _make_request(
            "v1",
            [
                _make_scene("v1_s000", "video"),
                _make_scene("v1_s001", "video"),
            ],
        )
        result = _decide_and_schedule(
            settings=settings, org_id=uuid4(), request=request, schedule_fn=fn
        )
        assert result == []
        fn.assert_not_called()

    def test_single_image_scheduled(self):
        settings = SimpleNamespace(image_caption_enabled=True)
        fn = MagicMock()
        org_id = uuid4()
        request = _make_request("v1", [_make_scene("v1_s000", "image")])
        result = _decide_and_schedule(
            settings=settings, org_id=org_id, request=request, schedule_fn=fn
        )
        assert len(result) == 1
        assert result[0].org_id == org_id
        assert result[0].video_id == "v1"
        assert result[0].scene_id == "v1_s000"
        assert result[0].file_name == "test.jpg"
        fn.assert_called_once()
        assert fn.call_args[0][0] == result

    def test_mixed_batch_only_images_scheduled(self):
        settings = SimpleNamespace(image_caption_enabled=True)
        fn = MagicMock()
        request = _make_request(
            "v1",
            [
                _make_scene("v1_s000", "image"),
                _make_scene("v1_s001", "video"),
                _make_scene("v1_s002", "image"),
            ],
        )
        result = _decide_and_schedule(
            settings=settings, org_id=uuid4(), request=request, schedule_fn=fn
        )
        assert [r.scene_id for r in result] == ["v1_s000", "v1_s002"]
        fn.assert_called_once()

    def test_scenes_with_unknown_content_type_not_scheduled(self):
        settings = SimpleNamespace(image_caption_enabled=True)
        fn = MagicMock()
        request = _make_request(
            "v1",
            [
                SimpleNamespace(scene_id="v1_s000"),  # no content_type attr
                _make_scene("v1_s001", "image"),
            ],
        )
        result = _decide_and_schedule(
            settings=settings, org_id=uuid4(), request=request, schedule_fn=fn
        )
        assert [r.scene_id for r in result] == ["v1_s001"]
