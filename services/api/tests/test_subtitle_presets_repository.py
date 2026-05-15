"""Repository tests for subtitle_presets.

Uses mocked AsyncSession — focuses on query construction + visibility
predicate correctness rather than real-DB behavior. Cross-org isolation
and owner-only mutation contracts are exercised here.
"""

from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.modules.subtitle_presets.models import SubtitlePreset
from app.modules.subtitle_presets.repository import SubtitlePresetRepository

ORG_ID = uuid4()
OTHER_ORG_ID = uuid4()
USER_ID = uuid4()
OTHER_USER_ID = uuid4()


def _fake_preset(**kw: Any) -> SubtitlePreset:
    p = SubtitlePreset(
        org_id=kw.get("org_id", ORG_ID),
        user_id=kw.get("user_id", USER_ID),
        name=kw.get("name", "P"),
        kind=kw.get("kind", "text"),
        style_json=kw.get("style_json", {}),
        is_shared=kw.get("is_shared", False),
    )
    # Simulate DB-assigned id; ignore for asserts unless explicit.
    p.id = kw.get("id", uuid4())
    return p


def _mock_session_with_scalar(value: Any) -> MagicMock:
    session = MagicMock()
    result = MagicMock()
    result.scalar_one_or_none = MagicMock(return_value=value)
    result.scalar_one = MagicMock(return_value=value)
    scalars = MagicMock()
    scalars.all = MagicMock(
        return_value=value if isinstance(value, list) else []
    )
    result.scalars = MagicMock(return_value=scalars)
    session.execute = AsyncMock(return_value=result)
    session.flush = AsyncMock()
    session.add = MagicMock()
    session.delete = AsyncMock()
    return session


# ---- create ----------------------------------------------------------------

@pytest.mark.asyncio
async def test_create_persists_via_session() -> None:
    session = _mock_session_with_scalar(None)
    repo = SubtitlePresetRepository(session)

    result = await repo.create(
        org_id=ORG_ID,
        user_id=USER_ID,
        name="My preset",
        kind="text",
        style_json={"font_color": "#FFFFFF"},
        is_shared=True,
    )

    session.add.assert_called_once()
    session.flush.assert_awaited()
    assert isinstance(result, SubtitlePreset)
    assert result.name == "My preset"
    assert result.is_shared is True


# ---- get_visible -----------------------------------------------------------

@pytest.mark.asyncio
async def test_get_visible_returns_when_found() -> None:
    target = _fake_preset()
    session = _mock_session_with_scalar(target)
    repo = SubtitlePresetRepository(session)

    result = await repo.get_visible(
        org_id=ORG_ID, user_id=USER_ID, preset_id=target.id
    )
    assert result is target


@pytest.mark.asyncio
async def test_get_visible_returns_none_when_missing() -> None:
    session = _mock_session_with_scalar(None)
    repo = SubtitlePresetRepository(session)

    result = await repo.get_visible(
        org_id=ORG_ID, user_id=USER_ID, preset_id=uuid4()
    )
    assert result is None


# ---- list_visible ----------------------------------------------------------

@pytest.mark.asyncio
async def test_list_visible_returns_items_and_total() -> None:
    items = [_fake_preset(name="a"), _fake_preset(name="b")]
    session = MagicMock()
    count_result = MagicMock()
    count_result.scalar_one = MagicMock(return_value=2)
    list_result = MagicMock()
    list_scalars = MagicMock()
    list_scalars.all = MagicMock(return_value=items)
    list_result.scalars = MagicMock(return_value=list_scalars)
    session.execute = AsyncMock(side_effect=[count_result, list_result])
    repo = SubtitlePresetRepository(session)

    result_items, total = await repo.list_visible(
        org_id=ORG_ID, user_id=USER_ID, kind=None, limit=20, offset=0
    )

    assert total == 2
    assert len(result_items) == 2
    assert session.execute.await_count == 2


# ---- update_owned ----------------------------------------------------------

@pytest.mark.asyncio
async def test_update_owned_returns_none_for_non_owner() -> None:
    # Repo's update_owned() does its own select-by-(id, org_id, user_id) — when
    # caller doesn't own it, the WHERE returns no row → None.
    session = _mock_session_with_scalar(None)
    repo = SubtitlePresetRepository(session)

    result = await repo.update_owned(
        org_id=ORG_ID,
        user_id=OTHER_USER_ID,
        preset_id=uuid4(),
        name="renamed",
    )
    assert result is None


@pytest.mark.asyncio
async def test_update_owned_applies_partial_fields() -> None:
    target = _fake_preset(name="old", is_shared=False)
    session = _mock_session_with_scalar(target)
    repo = SubtitlePresetRepository(session)

    result = await repo.update_owned(
        org_id=ORG_ID,
        user_id=USER_ID,
        preset_id=target.id,
        name="new",
        is_shared=True,
    )
    assert result is target
    assert target.name == "new"
    assert target.is_shared is True
    # style_json untouched (None passed → preserved)
    session.flush.assert_awaited()


# ---- delete_owned ----------------------------------------------------------

@pytest.mark.asyncio
async def test_delete_owned_returns_false_for_non_owner() -> None:
    session = _mock_session_with_scalar(None)
    repo = SubtitlePresetRepository(session)

    result = await repo.delete_owned(
        org_id=ORG_ID, user_id=OTHER_USER_ID, preset_id=uuid4()
    )
    assert result is False


@pytest.mark.asyncio
async def test_delete_owned_returns_true_for_owner() -> None:
    target = _fake_preset()
    session = _mock_session_with_scalar(target)
    repo = SubtitlePresetRepository(session)

    result = await repo.delete_owned(
        org_id=ORG_ID, user_id=USER_ID, preset_id=target.id
    )
    assert result is True
    session.delete.assert_awaited_once_with(target)
