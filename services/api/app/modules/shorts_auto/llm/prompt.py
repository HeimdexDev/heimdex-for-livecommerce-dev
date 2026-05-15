"""Prompt construction for the LLM scene picker.

Layout is intentionally stable-prefix → variable-suffix so OpenAI's
automatic prompt caching kicks in on the system message and most of
the user message. Bump ``PROMPT_VERSION`` on any semantic change; the
eval harness keys goldens on this version.

Never embed the scene corpus in the system message — it varies per
video and would defeat caching.
"""

from __future__ import annotations

from heimdex_media_contracts.scenes.schemas import SceneDocument
from heimdex_media_contracts.shorts.scorer import ScoringMode

# Bump on any semantic change to the system message or scene formatting.
# Goldens in tests/shorts_auto/eval/goldens/ are keyed on this string.
PROMPT_VERSION = "2026-04-24-v1"


_SYSTEM_MESSAGE = """\
You are an editor selecting clips for a short-form Korean livecommerce video.

Your job: from the provided scene list, pick the BEST scenes to combine
into a single short (target ~60 seconds, hard cap 90s total).

Rules:
- Only return scene_ids that appear EXACTLY in the input list. Never
  invent an id. If you cannot find enough good scenes, return fewer.
- Favor scenes with on-screen product demonstrations, clear Korean
  narration (transcript), and visible key info (OCR). Avoid
  scenes that are dead air, intros/outros, or duplicate content.
- Respect the requested mode:
    * human  — focus on the specified host (speaker continuity)
    * product — focus on product display and features (no hosts)
    * both   — rank on overall retention potential
- Return compact reasons (<= 30 Korean characters) per pick.
- The downstream concatenator packs picks chronologically; you don't
  need to order them, but do not pick 10+ tiny scenes when 4-6 longer
  ones tell the same story.

Output format: strict JSON matching the provided schema. No commentary,
no markdown fences."""


def system_message() -> str:
    return _SYSTEM_MESSAGE


def _format_scene(i: int, scene: SceneDocument) -> str:
    caption = (scene.scene_caption or "").strip()
    transcript = (scene.transcript_norm or scene.transcript_raw or "").strip()
    ocr = (scene.ocr_text_raw or "").strip()
    product_tags = ", ".join(scene.product_tags or [])
    keyword_tags = ", ".join(scene.keyword_tags or [])
    product_entities = ", ".join(scene.product_entities or [])
    people = ", ".join(scene.people_cluster_ids or [])
    duration_s = max(0, (scene.end_ms - scene.start_ms)) / 1000

    parts = [
        f"#{i} scene_id={scene.scene_id} start={scene.start_ms}ms end={scene.end_ms}ms dur={duration_s:.1f}s"
    ]
    if caption:
        parts.append(f"  caption: {caption[:200]}")
    if transcript:
        parts.append(f"  transcript: {transcript[:200]}")
    if ocr:
        parts.append(f"  ocr: {ocr[:120]}")
    if product_tags:
        parts.append(f"  product_tags: {product_tags}")
    if product_entities:
        parts.append(f"  product_entities: {product_entities[:120]}")
    if keyword_tags:
        parts.append(f"  keyword_tags: {keyword_tags}")
    if people:
        parts.append(f"  people: {people}")
    return "\n".join(parts)


def build_prompt(
    *,
    scenes: list[SceneDocument],
    mode: ScoringMode,
    target_duration_sec: int,
    video_id: str,
    video_title: str | None,
    person_cluster_id: str | None,
) -> list[dict[str, str]]:
    """Return OpenAI chat messages. System prompt is stable across calls
    for a given PROMPT_VERSION (cacheable). Scene list comes last.
    """
    header_lines = [
        f"video_id: {video_id}",
        f"video_title: {video_title or '(untitled)'}",
        f"mode: {mode.value}",
        f"target_duration_sec: {target_duration_sec}",
    ]
    if person_cluster_id:
        header_lines.append(f"target_person_cluster_id: {person_cluster_id}")
    header = "\n".join(header_lines)

    scene_block = "\n\n".join(
        _format_scene(i, scene) for i, scene in enumerate(scenes, start=1)
    )

    user_message = (
        f"Context:\n{header}\n\n"
        f"Candidate scenes ({len(scenes)} total):\n{scene_block}\n\n"
        "Pick the best scenes and return JSON per the schema."
    )

    return [
        {"role": "system", "content": _SYSTEM_MESSAGE},
        {"role": "user", "content": user_message},
    ]
