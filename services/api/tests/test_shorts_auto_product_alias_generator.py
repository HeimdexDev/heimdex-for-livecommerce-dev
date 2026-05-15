"""Unit tests for the spoken-form alias generator (PR 1b).

Pure unit tests — no DB, no real OpenAI, no real S3. The generator
takes ``openai_client`` + ``s3_client`` as constructor args precisely
so we can hand it fakes here. The repository write path is exercised
in a separate integration test (``test_shorts_auto_product_alias_repository.py``).

Coverage targets per plan §"Unit tests":
  - happy path returns parsed AliasGenerationResult
  - empty bytes from S3 → terminal
  - oversized bytes from S3 → terminal
  - boto NoSuchKey-shaped error → terminal (not retryable)
  - boto network-shaped error → retryable
  - JSON parse failure → terminal
  - schema validation failure (sentence-shaped alias) → terminal
  - openai timeout-shaped error → retryable
  - openai 4xx-shaped error → terminal
  - low-detail image flag is set on the request
  - the contracts AliasGenerationResponse is what we re-validate against
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import pytest

from app.modules.shorts_auto_product.aliases import (
    AliasGenerationRetryable,
    AliasGenerationTerminal,
    AliasGenerator,
)


# ---------- fakes ----------

class _FakeS3Client:
    def __init__(self, *, payload: bytes | None = b"\xff\xd8\xffbytes"):
        # The default payload is a fake JPEG header — content doesn't
        # matter, only that the generator base64-encodes it cleanly.
        self._payload = payload
        self.calls: list[str] = []

    def get_object_bytes(self, s3_key: str) -> bytes | None:
        self.calls.append(s3_key)
        return self._payload


class _FakeS3ClientRaising:
    def __init__(self, exc: Exception):
        self._exc = exc

    def get_object_bytes(self, s3_key: str) -> bytes | None:
        raise self._exc


@dataclass
class _Usage:
    prompt_tokens: int = 700
    completion_tokens: int = 40
    prompt_tokens_details: Any = None


@dataclass
class _Message:
    content: str


@dataclass
class _Choice:
    message: _Message


@dataclass
class _Response:
    choices: list[_Choice]
    usage: _Usage = field(default_factory=_Usage)


class _FakeChatCompletions:
    def __init__(self, raw_text: str | None = None, *, raises: Exception | None = None):
        self._raw = raw_text
        self._raises = raises
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> _Response:
        self.calls.append(kwargs)
        if self._raises is not None:
            raise self._raises
        text = self._raw if self._raw is not None else json.dumps({"aliases": ["달심"]})
        return _Response(choices=[_Choice(message=_Message(content=text))])


class _FakeChatNs:
    def __init__(self, completions: _FakeChatCompletions):
        self.completions = completions


class _FakeOpenAI:
    def __init__(self, *, raw_text: str | None = None, raises: Exception | None = None):
        self.completions = _FakeChatCompletions(raw_text=raw_text, raises=raises)
        self.chat = _FakeChatNs(self.completions)


# Generic fake exceptions to stand in for openai.* error types without
# importing the SDK in tests. The generator's ``_classify_openai_error``
# falls back to ``status_code`` attribute when openai SDK types are
# absent, so these reproduce that classification path.
class _FakeNetworkError(Exception):
    status_code = 503


class _Fake4xxError(Exception):
    status_code = 400


# ---------- tests ----------


@pytest.mark.asyncio
async def test_happy_path_returns_aliases_and_metadata():
    fake_openai = _FakeOpenAI(
        raw_text=json.dumps({"aliases": ["달심", "Dalsim", "이 주스"]}),
    )
    fake_s3 = _FakeS3Client()
    gen = AliasGenerator(openai_client=fake_openai, s3_client=fake_s3)

    result = await gen.generate(
        canonical_crop_s3_key="proxies/x/canonical.jpg",
        llm_label="달심 ABC 주스",
    )

    assert result.aliases == ["달심", "Dalsim", "이 주스"]
    assert result.prompt_version  # mirrored constant, not empty
    assert result.model == "gpt-4o-mini"
    # Cost is non-zero given the fake usage tokens.
    assert result.cost_usd > 0
    assert result.latency_ms >= 0
    # S3 fetch happened against the right key.
    assert fake_s3.calls == ["proxies/x/canonical.jpg"]


@pytest.mark.asyncio
async def test_low_detail_image_flag_passed_to_openai():
    """The image_detail='low' choice cuts vision token cost ~10×.
    A regression to 'high' would silently break the cost model.
    """
    fake_openai = _FakeOpenAI()
    fake_s3 = _FakeS3Client()
    gen = AliasGenerator(openai_client=fake_openai, s3_client=fake_s3)

    await gen.generate(
        canonical_crop_s3_key="proxies/x/canonical.jpg",
        llm_label="달심",
    )

    [call] = fake_openai.completions.calls
    user_msg = call["messages"][1]
    image_part = next(p for p in user_msg["content"] if p["type"] == "image_url")
    assert image_part["image_url"]["detail"] == "low"
    # The image is sent as a base64 data URL, never a raw S3 URL.
    assert image_part["image_url"]["url"].startswith("data:image/jpeg;base64,")


@pytest.mark.asyncio
async def test_label_substituted_into_user_template():
    fake_openai = _FakeOpenAI()
    fake_s3 = _FakeS3Client()
    gen = AliasGenerator(openai_client=fake_openai, s3_client=fake_s3)

    await gen.generate(
        canonical_crop_s3_key="proxies/x/canonical.jpg",
        llm_label="닥터포헤어 폴리젠 샴푸",
    )
    [call] = fake_openai.completions.calls
    user_text_part = call["messages"][1]["content"][0]
    assert user_text_part["type"] == "text"
    assert "닥터포헤어 폴리젠 샴푸" in user_text_part["text"]


@pytest.mark.asyncio
async def test_strict_json_schema_passed_to_openai():
    """OpenAI's strict mode rejects ``additionalProperties: true``;
    a regression would let hallucinated extra fields through and
    poison the catalog.
    """
    fake_openai = _FakeOpenAI()
    fake_s3 = _FakeS3Client()
    gen = AliasGenerator(openai_client=fake_openai, s3_client=fake_s3)

    await gen.generate(
        canonical_crop_s3_key="proxies/x/canonical.jpg", llm_label="달심",
    )
    [call] = fake_openai.completions.calls
    rf = call["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"]["additionalProperties"] is False
    assert rf["json_schema"]["schema"]["properties"]["aliases"]["maxItems"] == 10


# ---------- S3 failure modes ----------


@pytest.mark.asyncio
async def test_s3_returns_none_is_terminal():
    fake_s3 = _FakeS3Client(payload=None)
    gen = AliasGenerator(openai_client=_FakeOpenAI(), s3_client=fake_s3)
    with pytest.raises(AliasGenerationTerminal, match="None"):
        await gen.generate(
            canonical_crop_s3_key="proxies/missing.jpg", llm_label="x",
        )


@pytest.mark.asyncio
async def test_s3_returns_empty_bytes_is_terminal():
    fake_s3 = _FakeS3Client(payload=b"")
    gen = AliasGenerator(openai_client=_FakeOpenAI(), s3_client=fake_s3)
    with pytest.raises(AliasGenerationTerminal, match="empty"):
        await gen.generate(
            canonical_crop_s3_key="proxies/empty.jpg", llm_label="x",
        )


@pytest.mark.asyncio
async def test_s3_returns_oversized_bytes_is_terminal():
    fake_s3 = _FakeS3Client(payload=b"\x00" * (6 * 1024 * 1024))  # 6 MB
    gen = AliasGenerator(openai_client=_FakeOpenAI(), s3_client=fake_s3)
    with pytest.raises(AliasGenerationTerminal, match="too large"):
        await gen.generate(
            canonical_crop_s3_key="proxies/big.jpg", llm_label="x",
        )


@pytest.mark.asyncio
async def test_s3_no_such_key_is_terminal_not_retryable():
    """A wrong canonical_crop_s3_key is permanent — retrying would
    just hit the same 404. Classification by message content
    (avoids importing botocore in this module).
    """
    fake_s3 = _FakeS3ClientRaising(Exception("boom: NoSuchKey"))
    gen = AliasGenerator(openai_client=_FakeOpenAI(), s3_client=fake_s3)
    with pytest.raises(AliasGenerationTerminal, match="missing"):
        await gen.generate(
            canonical_crop_s3_key="proxies/gone.jpg", llm_label="x",
        )


@pytest.mark.asyncio
async def test_s3_network_error_is_retryable():
    fake_s3 = _FakeS3ClientRaising(
        ConnectionError("connection reset by peer"),
    )
    gen = AliasGenerator(openai_client=_FakeOpenAI(), s3_client=fake_s3)
    with pytest.raises(AliasGenerationRetryable, match="s3 download failed"):
        await gen.generate(
            canonical_crop_s3_key="proxies/x.jpg", llm_label="x",
        )


# ---------- LLM failure modes ----------


@pytest.mark.asyncio
async def test_json_parse_failure_is_terminal():
    """Strict-mode OpenAI shouldn't return malformed JSON, but if it
    does (e.g., model returns a markdown code fence), retrying with
    the same prompt + same image won't help.
    """
    fake_openai = _FakeOpenAI(raw_text="not json at all")
    fake_s3 = _FakeS3Client()
    gen = AliasGenerator(openai_client=fake_openai, s3_client=fake_s3)
    with pytest.raises(AliasGenerationTerminal, match="json_parse_failed"):
        await gen.generate(
            canonical_crop_s3_key="proxies/x.jpg", llm_label="x",
        )


@pytest.mark.asyncio
async def test_schema_validation_failure_is_terminal():
    """Sentence-shaped alias violates the contracts validator's 30-char
    cap. Generator must surface the failure as terminal — silently
    accepting it would over-match transcripts (BM25 noise).
    """
    long_alias = "이 제품은 정말 좋은 제품이고 모든 분께 추천하는 베스트셀러 제품입니다"
    assert len(long_alias) > 30  # fixture sanity
    fake_openai = _FakeOpenAI(
        raw_text=json.dumps({"aliases": [long_alias]}),
    )
    fake_s3 = _FakeS3Client()
    gen = AliasGenerator(openai_client=fake_openai, s3_client=fake_s3)
    with pytest.raises(AliasGenerationTerminal, match="schema_validation_failed"):
        await gen.generate(
            canonical_crop_s3_key="proxies/x.jpg", llm_label="x",
        )


@pytest.mark.asyncio
async def test_openai_5xx_is_retryable():
    fake_openai = _FakeOpenAI(raises=_FakeNetworkError("503 Service Unavailable"))
    fake_s3 = _FakeS3Client()
    gen = AliasGenerator(openai_client=fake_openai, s3_client=fake_s3)
    with pytest.raises(AliasGenerationRetryable):
        await gen.generate(
            canonical_crop_s3_key="proxies/x.jpg", llm_label="x",
        )


@pytest.mark.asyncio
async def test_openai_4xx_is_terminal():
    fake_openai = _FakeOpenAI(raises=_Fake4xxError("400 Bad Request"))
    fake_s3 = _FakeS3Client()
    gen = AliasGenerator(openai_client=fake_openai, s3_client=fake_s3)
    with pytest.raises(AliasGenerationTerminal):
        await gen.generate(
            canonical_crop_s3_key="proxies/x.jpg", llm_label="x",
        )


# ---------- contracts boundary ----------


@pytest.mark.asyncio
async def test_empty_alias_list_from_llm_is_accepted():
    """Per the prompt's empty-list-on-failure rule, gpt-4o-mini may
    legitimately return ``[]`` for an unreadable image. The generator
    must NOT treat that as an error — the catalog row gets persisted
    with empty aliases + ``aliases_generated_at`` set, which prevents
    a runaway retry loop on the same image.
    """
    fake_openai = _FakeOpenAI(raw_text=json.dumps({"aliases": []}))
    fake_s3 = _FakeS3Client()
    gen = AliasGenerator(openai_client=fake_openai, s3_client=fake_s3)

    result = await gen.generate(
        canonical_crop_s3_key="proxies/blurry.jpg", llm_label="?",
    )
    assert result.aliases == []


@pytest.mark.asyncio
async def test_dedupe_and_strip_via_contracts_validator():
    """The contracts validator strips empties and dedupes
    case-insensitively. The generator hands raw LLM output to the
    contracts model, so this test pins that the validator is
    actually invoked (not bypassed by some intermediate dataclass).
    """
    fake_openai = _FakeOpenAI(
        raw_text=json.dumps({"aliases": ["Dalsim", "dalsim", "  ", "달심"]}),
    )
    fake_s3 = _FakeS3Client()
    gen = AliasGenerator(openai_client=fake_openai, s3_client=fake_s3)

    result = await gen.generate(
        canonical_crop_s3_key="proxies/x.jpg", llm_label="x",
    )
    # First-occurrence-wins per casefold, empties dropped.
    assert result.aliases == ["Dalsim", "달심"]


@pytest.mark.asyncio
async def test_prompt_version_matches_contracts_constant():
    """The persisted ``aliases_prompt_version`` MUST match the
    contracts module constant — that's the entire mechanism for
    "stale-row re-generation after a prompt bump" to work.
    """
    from heimdex_media_contracts.product import ALIAS_GENERATION_PROMPT_VERSION

    fake_openai = _FakeOpenAI()
    fake_s3 = _FakeS3Client()
    gen = AliasGenerator(openai_client=fake_openai, s3_client=fake_s3)

    result = await gen.generate(
        canonical_crop_s3_key="proxies/x.jpg", llm_label="x",
    )
    assert result.prompt_version == ALIAS_GENERATION_PROMPT_VERSION
    assert gen.prompt_version == ALIAS_GENERATION_PROMPT_VERSION
