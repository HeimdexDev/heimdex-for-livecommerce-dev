"""PR 2.5 — child runner STT-branch tests.

Verifies the runner's track_mode='stt' branch:
  * routes to ``_process_child_stt`` only when the flag is set
  * passes the catalog entry's llm_label + spoken_aliases through
  * maps each STT error class to the right terminal action
  * builds the OS + OpenAI clients per-call and tears them down
  * persists ``render_job_id`` on success

Strategy mirrors ``test_shorts_auto_product_child_runner.py``: no
real Postgres, no real OpenSearch, no real OpenAI. Repos are
MagicMock'd; `assemble_stt_clip` is monkeypatched.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest

from app.modules.shorts_auto_product.children.runner import ChildRunner
from app.modules.shorts_auto_product.track_stt.errors import (
    NoMentionsFoundError,
    SttPipelineError,
    TranscriptUnavailableError,
)
from app.modules.shorts_auto_product.track_stt.models import SttClipResult


# ---------- helpers ----------


def _settings_stub(*, track_mode: str = "stt"):
    s = MagicMock()
    s.auto_shorts_product_v2_child_runner_max_concurrency = 4
    s.auto_shorts_product_v2_child_runner_poll_seconds = 0.05
    s.auto_shorts_product_v2_child_lease_seconds = 300
    s.auto_shorts_product_v2_child_runner_enabled = True
    s.auto_shorts_product_v2_track_mode = track_mode
    # Storyboard mode default-off for the legacy STT path tests —
    # ``getattr`` on a bare MagicMock would otherwise return a
    # truthy MagicMock and the factory would try to build a picker
    # with a mock-typed picker name (raises ValueError).
    s.auto_shorts_product_v2_storyboard_mode_enabled = False
    s.auto_shorts_product_v2_storyboard_picker = "heuristic"
    s.auto_shorts_product_v2_storyboard_shadow_mode = False
    s.auto_shorts_product_v2_storyboard_hook_ms = 8_000
    s.auto_shorts_product_v2_storyboard_intro_ms = 12_000
    s.auto_shorts_product_v2_storyboard_detail_ms = 25_000
    s.auto_shorts_product_v2_storyboard_cta_ms = 8_000
    s.auto_shorts_product_v2_legacy_os_subtitles_enabled = False
    s.openai_api_key = "sk-test"
    s.opensearch_url = "http://localhost:9200"
    s.opensearch_index_prefix = "heimdex"
    return s


def _mock_session_factory():
    @asynccontextmanager
    async def factory():
        session = MagicMock()
        session.commit = AsyncMock()
        yield session

    return factory


def _build_runner(*, settings=None):
    return ChildRunner(
        settings=settings or _settings_stub(),
        session_factory=_mock_session_factory(),
        scene_search_client=MagicMock(),
        instance_id="test-replica",
    )


# ---------- routing tests ----------


@pytest.mark.asyncio
async def test_stt_branch_invoked_when_flag_set(monkeypatch):
    """track_mode='stt' must route to _process_child_stt and bypass
    the SAM2 path's _load_appearances_for_catalog call.
    """
    runner = _build_runner(settings=_settings_stub(track_mode="stt"))

    # Spy on both branches.
    stt_called = AsyncMock()
    monkeypatch.setattr(runner, "_process_child_stt", stt_called)

    # Make sure the SAM2 step would crash if it ran — it shouldn't.
    sam2_loader = AsyncMock(side_effect=AssertionError("SAM2 path must not run"))
    monkeypatch.setattr(runner, "_load_appearances_for_catalog", sam2_loader)

    # Wire enough of the upstream to reach the branch.
    child = MagicMock(id=uuid4(), shorts_index=1)
    parent = MagicMock(
        org_id=uuid4(),
        video_id=uuid4(),
        product_distribution=None,
        length_seconds=60,
        duration_preset_sec=None,
        requested_by_user_id=uuid4(),
    )
    catalog_id = uuid4()
    catalog_label_lookup = {catalog_id: "Test product"}
    catalog_aliases_lookup = {catalog_id: ["Test product"]}
    monkeypatch.setattr(
        runner, "_load_child_context",
        AsyncMock(return_value=(child, parent, catalog_label_lookup, catalog_aliases_lookup)),
    )

    # Patch the repo class to return a fake that grants the claim.
    import app.modules.shorts_auto_product.children.runner as runner_module
    fake_repo = MagicMock()
    fake_repo.claim = AsyncMock(return_value=MagicMock())
    fake_repo.complete_tracking = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(
        runner_module, "ProductScanJobRepository",
        MagicMock(return_value=fake_repo),
    )
    # Picker has to return a deterministic catalog id.
    fake_picker = MagicMock()
    fake_picker.pick_catalog = MagicMock(return_value=MagicMock(catalog_entry_id=catalog_id))
    monkeypatch.setattr(
        runner_module, "SingleProductSubsetPicker",
        MagicMock(return_value=fake_picker),
    )

    await runner._process_child_payload(child.id)
    stt_called.assert_awaited_once()
    sam2_loader.assert_not_awaited()


@pytest.mark.asyncio
async def test_sam2_branch_unchanged_when_flag_default(monkeypatch):
    """track_mode='sam2' (default) must NOT route to _process_child_stt.
    Verifies PR 2.5 is purely additive when the flag is left alone.
    """
    runner = _build_runner(settings=_settings_stub(track_mode="sam2"))

    stt_called = AsyncMock()
    monkeypatch.setattr(runner, "_process_child_stt", stt_called)

    # Stop the SAM2 path quickly — _load_appearances returns []
    # which routes to _complete_no_render. We just need to confirm
    # _process_child_stt is NOT called.
    monkeypatch.setattr(
        runner, "_load_appearances_for_catalog",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        runner, "_complete_no_render", AsyncMock(),
    )

    child = MagicMock(id=uuid4(), shorts_index=1)
    parent = MagicMock(
        org_id=uuid4(), video_id=uuid4(),
        product_distribution=None, length_seconds=60,
        duration_preset_sec=None,
        requested_by_user_id=uuid4(),
    )
    catalog_id = uuid4()
    monkeypatch.setattr(
        runner, "_load_child_context",
        AsyncMock(return_value=(child, parent, {catalog_id: "X"}, {catalog_id: ["X"]})),
    )

    import app.modules.shorts_auto_product.children.runner as runner_module
    fake_repo = MagicMock()
    fake_repo.claim = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(
        runner_module, "ProductScanJobRepository",
        MagicMock(return_value=fake_repo),
    )
    fake_picker = MagicMock()
    fake_picker.pick_catalog = MagicMock(return_value=MagicMock(catalog_entry_id=catalog_id))
    monkeypatch.setattr(
        runner_module, "SingleProductSubsetPicker",
        MagicMock(return_value=fake_picker),
    )

    await runner._process_child_payload(child.id)
    stt_called.assert_not_awaited()


# ---------- _process_child_stt happy path + error mapping ----------


def _stub_load_stt_inputs(monkeypatch, runner, *, video_id="gd_x", llm_label="달심", aliases=("이 주스",)):
    monkeypatch.setattr(
        runner, "_load_stt_inputs",
        AsyncMock(return_value=(video_id, llm_label, list(aliases))),
    )


def _stub_clients(monkeypatch, runner):
    """Replace the per-call client constructors with no-op fakes so
    we don't actually open network sockets in tests.
    """
    fake_os = AsyncMock()
    fake_os.close = AsyncMock()
    monkeypatch.setattr(runner, "_build_os_client", lambda: fake_os)

    # AsyncOpenAI is constructed inline inside _process_child_stt via
    # ``from openai import AsyncOpenAI``. Patch the class in the
    # openai module's namespace.
    import openai
    fake_openai = MagicMock()
    fake_openai.close = AsyncMock()
    monkeypatch.setattr(openai, "AsyncOpenAI", MagicMock(return_value=fake_openai))


def _lease_stub(*, heartbeat_ok: bool = True):
    lease = MagicMock()
    lease.set_stage = MagicMock()
    lease.heartbeat_now = AsyncMock(return_value=heartbeat_ok)
    return lease


@pytest.mark.asyncio
async def test_stt_happy_path_persists_render_job_id(monkeypatch):
    runner = _build_runner()

    _stub_load_stt_inputs(monkeypatch, runner)
    _stub_clients(monkeypatch, runner)

    expected_render_id = uuid4()

    # _create_render_job is the closure target. Stub to return the
    # expected id so the assemble_stt_clip fake can claim it.
    create_render_mock = AsyncMock(return_value=expected_render_id)
    monkeypatch.setattr(runner, "_create_render_job", create_render_mock)

    sentinel_spec = {"composition": "sentinel"}

    async def _fake_assemble(**kwargs):
        # Caller passes the closure — invoke it so the test exercises
        # the closure body. Without this, signature drift in
        # ``_create_render_job`` (e.g. a newly required kw-only arg)
        # would silently slip past — the staging 2026-05-06 incident.
        assert kwargs["llm_label"] == "달심"
        assert kwargs["spoken_aliases"] == ["이 주스"]
        assert kwargs["os_video_id"] == "gd_x"
        assert kwargs["target_duration_ms"] == 60_000
        rendered = await kwargs["enqueue_render"](sentinel_spec)
        assert rendered == expected_render_id
        return SttClipResult(
            render_job_id=rendered,
            selected_chunks=[],
            mentioned_scene_count=5,
            matched_aliases=["달심"],
        )

    import app.modules.shorts_auto_product.track_stt.service as stt_service
    monkeypatch.setattr(stt_service, "assemble_stt_clip", _fake_assemble)

    # Repo for the final complete_tracking call.
    import app.modules.shorts_auto_product.children.runner as runner_module
    fake_repo = MagicMock()
    fake_repo.complete_tracking = AsyncMock(return_value=MagicMock())
    monkeypatch.setattr(
        runner_module, "ProductScanJobRepository",
        MagicMock(return_value=fake_repo),
    )

    child = MagicMock(id=uuid4(), shorts_index=1)
    parent = MagicMock(
        org_id=uuid4(), video_id=uuid4(),
        length_seconds=60, duration_preset_sec=None,
        requested_by_user_id=uuid4(),
    )
    catalog_id = uuid4()

    await runner._process_child_stt(
        child=child, parent=parent,
        chosen_catalog_id=catalog_id,
        catalog_label="my product",
        catalog_aliases_lookup={catalog_id: ["my product"]},
        lease=_lease_stub(),
    )

    # complete_tracking called with the render id from the pipeline.
    fake_repo.complete_tracking.assert_awaited_once()
    kwargs = fake_repo.complete_tracking.await_args.kwargs
    assert kwargs["render_job_id"] == expected_render_id
    assert kwargs["job_id"] == child.id

    # The closure must forward all kwargs ``_create_render_job`` requires —
    # crucially ``scan_job_id``, added in migration 057. A future
    # required-kwarg addition would also surface here.
    create_render_mock.assert_awaited_once()
    enqueue_kwargs = create_render_mock.await_args.kwargs
    assert enqueue_kwargs["org_id"] == parent.org_id
    assert enqueue_kwargs["user_id"] == parent.requested_by_user_id
    assert enqueue_kwargs["os_video_id"] == "gd_x"
    assert enqueue_kwargs["title"] == "my product"
    assert enqueue_kwargs["composition_spec"] is sentinel_spec
    assert enqueue_kwargs["scan_job_id"] == child.id


@pytest.mark.asyncio
async def test_stt_no_mentions_routes_to_complete_no_render(monkeypatch):
    runner = _build_runner()
    _stub_load_stt_inputs(monkeypatch, runner)
    _stub_clients(monkeypatch, runner)

    async def _raise_no_mentions(**kwargs):
        raise NoMentionsFoundError("nothing matched")

    import app.modules.shorts_auto_product.track_stt.service as stt_service
    monkeypatch.setattr(stt_service, "assemble_stt_clip", _raise_no_mentions)

    no_render_called = AsyncMock()
    monkeypatch.setattr(runner, "_complete_no_render", no_render_called)
    fail_called = AsyncMock()
    monkeypatch.setattr(runner, "_mark_child_failed", fail_called)

    child = MagicMock(id=uuid4(), shorts_index=1)
    parent = MagicMock(
        org_id=uuid4(), video_id=uuid4(),
        length_seconds=60, duration_preset_sec=None,
        requested_by_user_id=uuid4(),
    )
    await runner._process_child_stt(
        child=child, parent=parent,
        chosen_catalog_id=uuid4(),
        catalog_label="x",
        catalog_aliases_lookup={},
        lease=_lease_stub(),
    )
    no_render_called.assert_awaited_once()
    assert no_render_called.await_args.kwargs["reason"] == "stt_no_mentions"
    fail_called.assert_not_awaited()


@pytest.mark.asyncio
async def test_stt_transcript_unavailable_routes_to_complete_no_render(monkeypatch):
    runner = _build_runner()
    _stub_load_stt_inputs(monkeypatch, runner)
    _stub_clients(monkeypatch, runner)

    async def _raise(**kwargs):
        raise TranscriptUnavailableError("no transcripts on this video")

    import app.modules.shorts_auto_product.track_stt.service as stt_service
    monkeypatch.setattr(stt_service, "assemble_stt_clip", _raise)

    no_render_called = AsyncMock()
    monkeypatch.setattr(runner, "_complete_no_render", no_render_called)

    child = MagicMock(id=uuid4(), shorts_index=1)
    parent = MagicMock(
        org_id=uuid4(), video_id=uuid4(),
        length_seconds=60, duration_preset_sec=None,
        requested_by_user_id=uuid4(),
    )
    await runner._process_child_stt(
        child=child, parent=parent,
        chosen_catalog_id=uuid4(),
        catalog_label="x",
        catalog_aliases_lookup={},
        lease=_lease_stub(),
    )
    no_render_called.assert_awaited_once()
    assert no_render_called.await_args.kwargs["reason"] == "stt_transcript_unavailable"


@pytest.mark.asyncio
async def test_stt_pipeline_error_marks_child_failed(monkeypatch):
    runner = _build_runner()
    _stub_load_stt_inputs(monkeypatch, runner)
    _stub_clients(monkeypatch, runner)

    async def _raise(**kwargs):
        raise SttPipelineError("os unreachable")

    import app.modules.shorts_auto_product.track_stt.service as stt_service
    monkeypatch.setattr(stt_service, "assemble_stt_clip", _raise)

    no_render_called = AsyncMock()
    monkeypatch.setattr(runner, "_complete_no_render", no_render_called)
    fail_called = AsyncMock()
    monkeypatch.setattr(runner, "_mark_child_failed", fail_called)

    child = MagicMock(id=uuid4(), shorts_index=1)
    parent = MagicMock(
        org_id=uuid4(), video_id=uuid4(),
        length_seconds=60, duration_preset_sec=None,
        requested_by_user_id=uuid4(),
    )
    await runner._process_child_stt(
        child=child, parent=parent,
        chosen_catalog_id=uuid4(),
        catalog_label="x",
        catalog_aliases_lookup={},
        lease=_lease_stub(),
    )
    fail_called.assert_awaited_once()
    no_render_called.assert_not_awaited()


@pytest.mark.asyncio
async def test_stt_inputs_missing_routes_to_complete_no_render(monkeypatch):
    """If the catalog entry vanished between picker and load, OR the
    drive_files row is missing, _process_child_stt must route to
    _complete_no_render with reason='stt_inputs_missing' rather than
    crashing or trying to call assemble_stt_clip.
    """
    runner = _build_runner()
    monkeypatch.setattr(
        runner, "_load_stt_inputs",
        AsyncMock(return_value=(None, None, [])),
    )
    no_render_called = AsyncMock()
    monkeypatch.setattr(runner, "_complete_no_render", no_render_called)

    # If assemble_stt_clip is called with bad inputs the test fails.
    import app.modules.shorts_auto_product.track_stt.service as stt_service
    monkeypatch.setattr(
        stt_service, "assemble_stt_clip",
        AsyncMock(side_effect=AssertionError("must not be called when inputs missing")),
    )

    child = MagicMock(id=uuid4(), shorts_index=1)
    parent = MagicMock(
        org_id=uuid4(), video_id=uuid4(),
        length_seconds=60, duration_preset_sec=None,
        requested_by_user_id=uuid4(),
    )
    await runner._process_child_stt(
        child=child, parent=parent,
        chosen_catalog_id=uuid4(),
        catalog_label="x",
        catalog_aliases_lookup={},
        lease=_lease_stub(),
    )
    no_render_called.assert_awaited_once()
    assert no_render_called.await_args.kwargs["reason"] == "stt_inputs_missing"


# ---------- _build_os_client smoke ----------


def test_build_os_client_returns_async_opensearch(monkeypatch):
    runner = _build_runner()
    client = runner._build_os_client()
    # Construction succeeded — the client object exists with the
    # expected duck-typed interface.
    assert hasattr(client, "search")
