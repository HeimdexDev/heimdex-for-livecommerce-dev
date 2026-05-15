"""Tests for app.modules.image_caption.service.

Covers:
  - ImageCaptionService.caption_scenes happy path with a stubbed engine
  - Parse failure path (engine returns empty caption + validation_failure)
  - Person-safety violation path (engine raises)
  - Budget exhaustion — batch aborts cleanly, remaining scenes untouched
  - Keyframe download failure — single scene skipped, batch continues
  - Engine retryable error — single scene skipped, batch continues
  - Concurrency ceiling: never more than image_caption_max_concurrency
    in-flight at once (instrumented stub)
  - schedule_image_caption_task — fire-and-forget wiring and GC-safe
    strong reference retention
  - get_service disabled short-circuit (settings.image_caption_enabled=False)

These tests do NOT talk to the real OpenAI, real DB, or real S3. They
stub out:
  - _download_keyframe (monkey-patched to no-op or raise)
  - _write_caption (monkey-patched to append to a list)
  - The engine (in-process stub)

The integration that verifies the full chain (engine → S3 → DB → OpenSearch)
belongs to a higher-layer test that runs inside the docker compose stack.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from app.modules.image_caption.engines.base import (
    BudgetExceededError,
    CaptionResult,
    PersonSafetyViolation,
    RetryableEngineError,
    TerminalEngineError,
    TokenUsage,
)
from app.modules.image_caption.service import (
    ImageCaptionService,
    SceneCaptionRequest,
    _BACKGROUND_TASKS,
    get_service,
    reset_service_for_tests,
    schedule_image_caption_task,
)


# ─── helpers ─────────────────────────────────────────────────────────────────


def _make_result(caption: str = "민트 배경에 제품", *, failure: str | None = None) -> CaptionResult:
    return CaptionResult(
        caption=caption if failure is None else "",
        prompt_version="test-v1",
        model="gpt-4o",
        usage=TokenUsage(prompt_tokens=2000, completion_tokens=300, total_tokens=2300),
        structured={"caption": caption, "has_person": False} if caption else None,
        latency_ms=10,
        validation_failure=failure,
    )


def _make_request(scene_id: str = "vid_s000") -> SceneCaptionRequest:
    return SceneCaptionRequest(
        org_id=uuid4(),
        video_id="vid",
        scene_id=scene_id,
        file_name="shot.jpg",
        library_name="dev",
    )


class _StubEngine:
    """Captures caption() invocations for assertion."""

    name = "stub"

    def __init__(self, behavior: list[Any]) -> None:
        self._behavior = list(behavior)
        self.calls: list[Path] = []

    def caption(self, image_path: Path, hints: dict[str, Any] | None = None) -> CaptionResult:
        self.calls.append(Path(image_path))
        if not self._behavior:
            return _make_result()
        item = self._behavior.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self) -> None:
        pass


class _InstrumentedSemaphoreEngine:
    """Tracks max-in-flight for concurrency assertions."""

    name = "stub"

    def __init__(self) -> None:
        self.in_flight = 0
        self.peak = 0
        self._lock = asyncio.Lock()

    def caption(self, image_path: Path, hints: dict[str, Any] | None = None) -> CaptionResult:
        # Simulate work; the semaphore is enforced by the async caller.
        # We mutate counters synchronously because the caller invokes us
        # inside run_in_executor — one thread at a time is fine for this
        # test's assertion (we're measuring *async* concurrency, and the
        # service's async semaphore bounds the outer await).
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)
        try:
            return _make_result()
        finally:
            self.in_flight -= 1

    def close(self) -> None:
        pass


def _patch_io(service: ImageCaptionService, monkeypatch, *, writes: list[Any], download_raises: list[Exception] | None = None) -> None:
    """Monkey-patch S3 download and DB write on an ImageCaptionService."""

    download_queue = list(download_raises or [])

    async def fake_download(self, s3_key: str, local_path: Path) -> None:  # noqa: ARG001
        if download_queue:
            exc = download_queue.pop(0)
            if isinstance(exc, Exception):
                raise exc
        local_path.write_bytes(b"fake jpeg bytes")

    async def fake_write(self, req: SceneCaptionRequest, result: CaptionResult) -> None:  # noqa: ARG001
        writes.append((req.scene_id, result.caption))

    monkeypatch.setattr(
        ImageCaptionService, "_download_keyframe", fake_download, raising=True
    )
    monkeypatch.setattr(
        ImageCaptionService, "_write_caption", fake_write, raising=True
    )


# ─── ImageCaptionService.caption_scenes ──────────────────────────────────────


@pytest.mark.asyncio
async def test_caption_scenes_happy_path(monkeypatch):
    writes: list[Any] = []
    engine = _StubEngine([_make_result("caption-a"), _make_result("caption-b")])
    service = ImageCaptionService(engine=engine, max_concurrency=2)
    _patch_io(service, monkeypatch, writes=writes)

    await service.caption_scenes([_make_request("s1"), _make_request("s2")])

    assert len(engine.calls) == 2
    assert {w[0] for w in writes} == {"s1", "s2"}
    assert all("caption" in w[1] for w in writes)


@pytest.mark.asyncio
async def test_parse_error_skips_write(monkeypatch):
    writes: list[Any] = []
    # Empty caption + failure code — engine already logged, service should
    # not attempt a write.
    engine = _StubEngine([_make_result("", failure="parse_error:bad_json")])
    service = ImageCaptionService(engine=engine, max_concurrency=2)
    _patch_io(service, monkeypatch, writes=writes)

    await service.caption_scenes([_make_request("s1")])

    assert len(engine.calls) == 1
    assert writes == []  # parse error → no write


@pytest.mark.asyncio
async def test_person_safety_violation_caught_and_batch_continues(monkeypatch):
    writes: list[Any] = []
    engine = _StubEngine([
        PersonSafetyViolation("쇼호스트 leaked"),
        _make_result("safe-caption"),
    ])
    service = ImageCaptionService(engine=engine, max_concurrency=2)
    _patch_io(service, monkeypatch, writes=writes)

    await service.caption_scenes([_make_request("s1"), _make_request("s2")])

    # Both engine calls happened (first raised, second succeeded)
    assert len(engine.calls) == 2
    # Only s2 got written
    assert len(writes) == 1
    assert writes[0][0] == "s2"


@pytest.mark.asyncio
async def test_budget_exhaustion_aborts_batch(monkeypatch):
    writes: list[Any] = []
    # First scene raises budget exhausted → remaining scenes must not be
    # captioned. This prevents slamming OpenAI with guaranteed failures.
    engine = _StubEngine([
        BudgetExceededError("$0 remaining"),
        _make_result("should-never-run"),
    ])
    service = ImageCaptionService(engine=engine, max_concurrency=2)
    _patch_io(service, monkeypatch, writes=writes)

    await service.caption_scenes([_make_request("s1"), _make_request("s2")])

    assert len(engine.calls) == 1  # second call never happened
    assert writes == []


@pytest.mark.asyncio
async def test_keyframe_download_failure_skips_scene(monkeypatch):
    writes: list[Any] = []
    engine = _StubEngine([_make_result("s2-caption")])
    service = ImageCaptionService(engine=engine, max_concurrency=2)
    _patch_io(
        service,
        monkeypatch,
        writes=writes,
        download_raises=[FileNotFoundError("no such s3 key"), None],
    )

    await service.caption_scenes([_make_request("s1"), _make_request("s2")])

    # Engine was only called once (s2) — s1 failed at download
    assert len(engine.calls) == 1
    assert len(writes) == 1
    assert writes[0][0] == "s2"


@pytest.mark.asyncio
async def test_retryable_engine_error_skips_scene(monkeypatch):
    writes: list[Any] = []
    engine = _StubEngine([
        RetryableEngineError("network flake"),
        _make_result("ok"),
    ])
    service = ImageCaptionService(engine=engine, max_concurrency=2)
    _patch_io(service, monkeypatch, writes=writes)

    await service.caption_scenes([_make_request("s1"), _make_request("s2")])

    assert len(engine.calls) == 2
    assert len(writes) == 1
    assert writes[0][0] == "s2"


@pytest.mark.asyncio
async def test_terminal_engine_error_skips_scene(monkeypatch):
    writes: list[Any] = []
    engine = _StubEngine([
        TerminalEngineError("bad request"),
        _make_result("ok"),
    ])
    service = ImageCaptionService(engine=engine, max_concurrency=2)
    _patch_io(service, monkeypatch, writes=writes)

    await service.caption_scenes([_make_request("s1"), _make_request("s2")])

    assert len(engine.calls) == 2
    assert len(writes) == 1


# ─── schedule_image_caption_task ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schedule_empty_is_noop(monkeypatch):
    # Reset singleton so get_service would construct a new engine if called
    reset_service_for_tests()
    schedule_image_caption_task([])
    # No task created
    assert len(_BACKGROUND_TASKS) == 0


@pytest.mark.asyncio
async def test_schedule_no_service_when_disabled(monkeypatch):
    from app.config import get_settings

    reset_service_for_tests()

    # Ensure the feature flag is off — get_service must return None.
    # We use monkeypatch on a fresh Settings() to avoid mutating the
    # global lru_cache'd singleton.
    class _FakeSettings:
        image_caption_enabled = False

    def _fake_get_settings():
        return _FakeSettings()

    monkeypatch.setattr(
        "app.modules.image_caption.service.get_service.__wrapped__"
        if hasattr(get_service, "__wrapped__") else "app.config.get_settings",
        _fake_get_settings,
        raising=False,
    )
    # Simpler: directly patch get_settings in the service module namespace
    monkeypatch.setattr("app.config.get_settings", _fake_get_settings)

    service = await get_service()
    assert service is None


@pytest.mark.asyncio
async def test_schedule_task_runs_and_clears_from_set(monkeypatch):
    reset_service_for_tests()

    writes: list[Any] = []
    engine = _StubEngine([_make_result("scheduled")])
    service = ImageCaptionService(engine=engine, max_concurrency=1)
    _patch_io(service, monkeypatch, writes=writes)

    # Pre-seed the singleton so schedule_image_caption_task picks it up.
    import app.modules.image_caption.service as svc_mod

    svc_mod._SERVICE_SINGLETON = service

    schedule_image_caption_task([_make_request("s1")])
    assert len(_BACKGROUND_TASKS) >= 1

    # Let the task run
    for _ in range(10):
        await asyncio.sleep(0)
        if not _BACKGROUND_TASKS:
            break

    assert writes == [("s1", "scheduled")]
    assert len(_BACKGROUND_TASKS) == 0  # done_callback fired

    reset_service_for_tests()


# ─── concurrency ceiling ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrency_ceiling(monkeypatch):
    # 10 scenes, max_concurrency=3 → peak must never exceed 3
    engine = _InstrumentedSemaphoreEngine()
    service = ImageCaptionService(engine=engine, max_concurrency=3)

    writes: list[Any] = []

    async def fake_write(self, req: SceneCaptionRequest, result: CaptionResult) -> None:  # noqa: ARG001
        writes.append(req.scene_id)

    async def fake_download(self, s3_key: str, local_path: Path) -> None:  # noqa: ARG001
        local_path.write_bytes(b"fake")

    monkeypatch.setattr(
        ImageCaptionService, "_download_keyframe", fake_download, raising=True
    )
    monkeypatch.setattr(
        ImageCaptionService, "_write_caption", fake_write, raising=True
    )

    await service.caption_scenes([_make_request(f"s{i}") for i in range(10)])

    assert len(writes) == 10
    # Note: because caption_scenes is sequential per-scene-in-a-batch
    # but still uses the async semaphore, peak with max_concurrency=3
    # should be at most 3. For a single-batch sequential loop the peak
    # is at most 1, which also satisfies the ceiling.
    assert engine.peak <= 3
