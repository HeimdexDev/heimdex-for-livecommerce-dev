"""Tests for app.cli.backfill_image_caption_batch.

Covers the pure functions (JSONL line construction, MIME guessing,
custom_id round-trip) with fixture data. The subcommand entry points
(prepare/submit/status/apply) are integration-heavy (DB, S3, OpenAI)
and are exercised in the docker compose integration lane, not here.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest

from app.cli.backfill_image_caption_batch import (
    ImageRow,
    _guess_mime,
    build_batch_request_line,
)


class TestGuessMime:
    @pytest.mark.parametrize(
        "name,expected",
        [
            ("photo.jpg", "image/jpeg"),
            ("PHOTO.JPEG", "image/jpeg"),
            ("shot.png", "image/png"),
            ("banner.webp", "image/webp"),
            ("icon.gif", "image/gif"),
            ("weird.bin", "image/jpeg"),
            ("", "image/jpeg"),
        ],
    )
    def test_cases(self, name, expected):
        assert _guess_mime(name) == expected


class TestBuildBatchRequestLine:
    def _row(self) -> ImageRow:
        return ImageRow(
            drive_file_id=uuid4(),
            org_id=uuid4(),
            video_id="vid123",
            file_name="brand_shot.jpg",
            scene_id="vid123_scene_000",
        )

    def _build(self, row: ImageRow):
        return build_batch_request_line(
            row=row,
            image_bytes=b"\xff\xd8fake",
            model="gpt-4o",
            image_detail="low",
            messages_prefix=[
                {"role": "system", "content": "sys"},
            ],
            user_instruction="please caption",
            json_schema={"name": "t", "strict": True, "schema": {}},
        )

    def test_custom_id_roundtrip_format(self):
        row = self._row()
        line = self._build(row)
        org, video, scene = line["custom_id"].split("::")
        assert org == str(row.org_id)
        assert video == row.video_id
        assert scene == row.scene_id

    def test_required_batch_fields(self):
        line = self._build(self._row())
        assert line["method"] == "POST"
        assert line["url"] == "/v1/chat/completions"
        body = line["body"]
        assert body["model"] == "gpt-4o"
        assert body["temperature"] == 0
        assert body["seed"] == 42
        assert body["response_format"]["type"] == "json_schema"

    def test_user_turn_contains_image_url_and_hint(self):
        line = self._build(self._row())
        messages = line["body"]["messages"]
        user_turn = messages[-1]
        assert user_turn["role"] == "user"
        parts = user_turn["content"]
        text_parts = [p for p in parts if p["type"] == "text"]
        image_parts = [p for p in parts if p["type"] == "image_url"]
        assert len(text_parts) == 1
        assert "brand_shot.jpg" in text_parts[0]["text"]
        assert len(image_parts) == 1
        url = image_parts[0]["image_url"]["url"]
        assert url.startswith("data:image/jpeg;base64,")
        assert image_parts[0]["image_url"]["detail"] == "low"

    def test_prefix_preserved_exactly(self):
        row = self._row()
        prefix = [
            {"role": "system", "content": "sys"},
            {"role": "user", "content": "fewshot-u"},
            {"role": "assistant", "content": "fewshot-a"},
        ]
        line = build_batch_request_line(
            row=row,
            image_bytes=b"bytes",
            model="gpt-4o",
            image_detail="low",
            messages_prefix=prefix,
            user_instruction="instr",
            json_schema={"name": "t", "strict": True, "schema": {}},
        )
        msgs = line["body"]["messages"]
        assert msgs[:-1] == prefix  # prefix unchanged
        assert msgs[-1]["role"] == "user"

    def test_json_serializable(self):
        line = self._build(self._row())
        # Must be JSON-serializable; OpenAI Batch API requires ASCII-safe
        # JSON in the input file or UTF-8 with escape. Either is fine —
        # but the call must not raise.
        s = json.dumps(line, ensure_ascii=False)
        assert len(s) > 0
        # And round-trip
        restored = json.loads(s)
        assert restored["custom_id"] == line["custom_id"]
