"""Versioned prompt templates for video summary generation."""

from __future__ import annotations

from dataclasses import dataclass

CURRENT_VERSION = "v1"


@dataclass(frozen=True)
class PromptTemplate:
    system: str
    user_template: str


PROMPTS: dict[str, PromptTemplate] = {
    "v1": PromptTemplate(
        system=(
            "You are a video content analyst for Korean live commerce. "
            "You summarize livestream videos based on scene-by-scene descriptions. "
            "Write in Korean. Be concise: 2-4 sentences. "
            "Focus on: what products are shown, what the host does, key selling points. "
            "Do not repeat the same information. Do not use bullet points or numbering."
        ),
        user_template=(
            "영상 제목: {video_title}\n\n"
            "장면별 설명 ({scene_count}개 장면):\n"
            "{numbered_captions}\n\n"
            "위 장면 설명을 바탕으로 이 영상의 내용을 2-4문장으로 요약해주세요."
        ),
    ),
}


def get_prompt(version: str | None = None) -> PromptTemplate:
    v = version or CURRENT_VERSION
    if v not in PROMPTS:
        raise ValueError(f"Unknown prompt version: {v}. Available: {list(PROMPTS.keys())}")
    return PROMPTS[v]
