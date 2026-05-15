"""Tests for ``GET /api/shorts/render/{job_id}/subtitles.{srt|vtt}``.

Companion to PR ``auto-shorts-subtitle-editor-2026-05-06.md`` —
exposes operator-edited subtitles as a downloadable SRT/VTT file so
post-render exports can be polished in NLE without re-rendering.

Direct route-function tests with mocked deps — the pattern used by
``test_shorts_render_subtitles_patch.py`` and ``test_rerender_from_edits.py``.
TestClient is intentionally avoided here so the test stays under
the project's no-docker-services CI gate.

Coverage:
  * 200 SRT — body uses comma-millisecond separator, attachment header,
    title-derived filename.
  * 200 VTT — body has WEBVTT header + dot-millisecond separator.
  * 200 with empty body when ``input_spec`` carries zero subtitles.
  * 404 when the service returns ``None`` (missing or non-owner).
  * Filename sanitization preserves Hangul + replaces unsafe chars.
  * RFC 5987 ``filename*`` is set so Korean titles survive the
    download dialog on every browser.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from fastapi.responses import PlainTextResponse

from app.modules.shorts_render.router import (
    _safe_subtitle_filename_stem,
    download_render_job_subtitles,
)


def _make_job(
    *,
    title: str | None = "Heimdex Mini",
    subtitles: list[dict] | None = None,
):
    return SimpleNamespace(
        id=uuid4(),
        title=title,
        input_spec={
            "scene_clips": [{"video_id": "gd_v1", "scene_id": "gd_v1_scene_000"}],
            "subtitles": subtitles or [],
        },
    )


def _make_user(user_id=None):
    user = MagicMock()
    user.id = user_id or uuid4()
    return user


def _make_org_ctx(org_id=None):
    return SimpleNamespace(org_id=org_id or uuid4())


# ---- Filename sanitization (pure helper) ----


class TestFilenameSanitisation:
    def test_keeps_hangul_and_alnum(self) -> None:
        # Real-world wizard title: product name with Hangul.
        assert _safe_subtitle_filename_stem("베노프 단백질") == "베노프-단백질"

    def test_replaces_punctuation_with_dash(self) -> None:
        # Title from EditClipsPage header: "Heimdex Mini · {hash}"
        out = _safe_subtitle_filename_stem("Heimdex Mini · 63ce2cbd")
        # Period, middle-dot, and space all collapse to dashes.
        assert out == "Heimdex-Mini-63ce2cbd"

    def test_strips_leading_and_trailing_dashes(self) -> None:
        assert _safe_subtitle_filename_stem("...messy...") == "messy"

    def test_falls_back_when_title_blank(self) -> None:
        assert _safe_subtitle_filename_stem("") == "subtitles"
        assert _safe_subtitle_filename_stem(None) == "subtitles"
        # A title that sanitises to all-dashes is also empty after strip.
        assert _safe_subtitle_filename_stem("   ...   ") == "subtitles"


# ---- Endpoint ----


class TestEndpoint:
    @pytest.mark.asyncio
    async def test_srt_returns_serialized_body(self) -> None:
        svc = MagicMock()
        svc.get_render_job_record = AsyncMock(
            return_value=_make_job(
                title="Heimdex Mini",
                subtitles=[
                    {"text": "안녕", "start_ms": 0, "end_ms": 1000},
                    {"text": "하세요", "start_ms": 1000, "end_ms": 2200},
                ],
            )
        )

        response = await download_render_job_subtitles(
            job_id=uuid4(),
            org_ctx=_make_org_ctx(),
            user=_make_user(),
            service=svc,
            fmt="srt",
        )

        assert isinstance(response, PlainTextResponse)
        body = response.body.decode("utf-8")
        assert body.startswith("1\n00:00:00,000 --> 00:00:01,000\n안녕\n")
        assert "2\n00:00:01,000 --> 00:00:02,200\n하세요\n" in body
        assert response.media_type == "application/x-subrip; charset=utf-8"
        cd = response.headers["content-disposition"]
        assert 'filename="subtitles.srt"' in cd
        # Korean filename is RFC 5987 percent-encoded; ASCII fallback is set
        # so unsupported clients still get a sensible default.
        assert "filename*=UTF-8''Heimdex-Mini.srt" in cd

    @pytest.mark.asyncio
    async def test_vtt_returns_webvtt_header_and_dot_separator(self) -> None:
        svc = MagicMock()
        svc.get_render_job_record = AsyncMock(
            return_value=_make_job(
                title="베노프 단백질",
                subtitles=[
                    {"text": "first", "start_ms": 250, "end_ms": 1000},
                ],
            )
        )

        response = await download_render_job_subtitles(
            job_id=uuid4(),
            org_ctx=_make_org_ctx(),
            user=_make_user(),
            service=svc,
            fmt="vtt",
        )

        body = response.body.decode("utf-8")
        assert body.startswith("WEBVTT\n")
        assert "00:00:00.250 --> 00:00:01.000" in body
        assert response.media_type == "text/vtt; charset=utf-8"
        # Korean title survives via RFC 5987 percent-encoding.
        cd = response.headers["content-disposition"]
        assert "%EB%B2%A0%EB%85%B8%ED%94%84" in cd  # 베노프 url-encoded

    @pytest.mark.asyncio
    async def test_empty_subtitles_returns_200_with_empty_body(self) -> None:
        # Image-only renders + legacy compositions have zero subtitles.
        # Operators see the empty-state copy in the editor; downloading
        # an empty file is preferable to 404 (less surprising — the job
        # exists, it just has no captions).
        svc = MagicMock()
        svc.get_render_job_record = AsyncMock(
            return_value=_make_job(subtitles=[])
        )

        response = await download_render_job_subtitles(
            job_id=uuid4(),
            org_ctx=_make_org_ctx(),
            user=_make_user(),
            service=svc,
            fmt="srt",
        )
        assert response.body == b""

    @pytest.mark.asyncio
    async def test_vtt_empty_keeps_header(self) -> None:
        # WebVTT players reject body-only files; we always emit the
        # header even when there are no cues.
        svc = MagicMock()
        svc.get_render_job_record = AsyncMock(
            return_value=_make_job(subtitles=[])
        )

        response = await download_render_job_subtitles(
            job_id=uuid4(),
            org_ctx=_make_org_ctx(),
            user=_make_user(),
            service=svc,
            fmt="vtt",
        )
        assert response.body == b"WEBVTT\n"

    @pytest.mark.asyncio
    async def test_404_when_service_returns_none(self) -> None:
        # Service returns None for both "row missing" AND "row not owned
        # by caller" — endpoint must not leak the distinction.
        svc = MagicMock()
        svc.get_render_job_record = AsyncMock(return_value=None)

        with pytest.raises(HTTPException) as excinfo:
            await download_render_job_subtitles(
                job_id=uuid4(),
                org_ctx=_make_org_ctx(),
                user=_make_user(),
                service=svc,
                fmt="srt",
            )
        assert excinfo.value.status_code == 404

    @pytest.mark.asyncio
    async def test_filename_falls_back_when_title_missing(self) -> None:
        svc = MagicMock()
        svc.get_render_job_record = AsyncMock(
            return_value=_make_job(
                title=None,
                subtitles=[{"text": "x", "start_ms": 0, "end_ms": 100}],
            )
        )
        response = await download_render_job_subtitles(
            job_id=uuid4(),
            org_ctx=_make_org_ctx(),
            user=_make_user(),
            service=svc,
            fmt="srt",
        )
        cd = response.headers["content-disposition"]
        assert 'filename="subtitles.srt"' in cd
        assert "filename*=UTF-8''subtitles.srt" in cd

    @pytest.mark.asyncio
    async def test_handles_input_spec_missing_subtitles_key(self) -> None:
        # Defensive: legacy compositions might not even carry the key.
        svc = MagicMock()
        job = _make_job(subtitles=None)
        job.input_spec = {"scene_clips": [{}]}  # no "subtitles" at all
        svc.get_render_job_record = AsyncMock(return_value=job)

        response = await download_render_job_subtitles(
            job_id=uuid4(),
            org_ctx=_make_org_ctx(),
            user=_make_user(),
            service=svc,
            fmt="srt",
        )
        assert response.body == b""
