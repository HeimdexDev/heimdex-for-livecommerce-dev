"""Isolated OpenAI API client for video summary generation.

No internal imports. Depends only on the openai SDK and standard library.
Fully mockable for testing.
"""

from __future__ import annotations

import hashlib

from openai import AsyncOpenAI


def compute_input_hash(captions: list[str]) -> str:
    joined = "\n".join(sorted(captions))
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


async def generate_video_summary(
    client: AsyncOpenAI,
    video_title: str,
    scene_captions: list[str],
    *,
    system_prompt: str,
    user_template: str,
    model: str = "gpt-4o-mini",
    max_tokens: int = 300,
) -> str:
    """Generate a video summary from scene captions via OpenAI.

    Args:
        client: AsyncOpenAI instance.
        video_title: Title of the video.
        scene_captions: List of non-empty scene caption strings.
        system_prompt: System message for the model.
        user_template: User message template with {video_title}, {scene_count}, {numbered_captions}.
        model: OpenAI model ID.
        max_tokens: Maximum output tokens.

    Returns:
        The generated summary text.
    """
    numbered = "\n".join(
        f"{i}. {cap}" for i, cap in enumerate(scene_captions, 1)
    )

    user_message = user_template.format(
        video_title=video_title or "(제목 없음)",
        scene_count=len(scene_captions),
        numbered_captions=numbered,
    )

    response = await client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        max_tokens=max_tokens,
        temperature=0.3,
    )

    return (response.choices[0].message.content or "").strip()
