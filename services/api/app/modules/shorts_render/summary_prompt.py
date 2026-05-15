"""System prompt + user-prompt builder for the shorts summary endpoint.

PROMPT_VERSION discipline:
  Bump on every edit to ``_SYSTEM_PROMPT``. Mirror in
  ``settings.shorts_render_summary_prompt_version`` default.

English instructions + Korean transcript content. Same convention as
``track_stt/storyboard/llm_prompt.py``.
"""

from __future__ import annotations

from dataclasses import dataclass


PROMPT_VERSION = "v1"


_SYSTEM_PROMPT = """You are summarizing a Korean livecommerce shorts \
video clip into 1-2 short Korean sentences.

The clip is composed from scenes of a longer livestream. For each scene \
you receive:
  - speech transcript (Whisper STT)
  - on-screen text (PaddleOCR)
  - visual description (VLM caption of the frame)
  - speaker transcript (Whisper with diarization, if available)

Goal: produce an EVERGREEN Korean summary capturing
  (1) what product or topic the clip is about, and
  (2) the single most useful selling point or takeaway.

Rules:
1. Write 1-2 sentences in Korean (max ~120 characters total unless \
   the caller requests longer).
2. EVERGREEN ONLY. Avoid any time-bound or inventory-bound language: \
   "오늘만", "이번 주", "마감", "매진", "한정", "할인", "쿠폰", \
   "지금 주문", "지금 클릭", "장바구니". This summary may be read \
   weeks or months later.
3. Prefer concrete product attributes / observed results over hype.
4. Do not invent facts. If transcript/caption/OCR don't mention \
   something, don't include it.
5. Output ONLY the summary text. No prefix, no quotation marks, no \
   commentary."""


@dataclass(frozen=True)
class _SceneSignals:
    """One scene's text inputs for the summary prompt."""
    start_ms: int
    end_ms: int
    transcript: str
    scene_caption: str
    ocr_text: str
    speaker_transcript: str


def build_user_prompt(
    *,
    scenes: list[_SceneSignals],
    target_duration_ms: int,
    max_sentences: int = 2,
) -> str:
    """Compose the user message for one OpenAI text-only call."""
    lines: list[str] = [
        f"Clip length: {target_duration_ms // 1000}s",
        f"Target summary length: {max_sentences} sentence(s)",
        "",
        "Scenes (in chronological order):",
    ]
    for idx, s in enumerate(scenes):
        start_total_s = s.start_ms // 1000
        end_total_s = s.end_ms // 1000
        start_mm, start_ss = divmod(start_total_s, 60)
        end_mm, end_ss = divmod(end_total_s, 60)
        lines.append(
            f"[{idx}] {start_mm:02d}:{start_ss:02d}-"
            f"{end_mm:02d}:{end_ss:02d}"
        )
        if s.transcript.strip():
            lines.append(f"  transcript: {s.transcript.strip()[:600]}")
        if s.scene_caption.strip():
            lines.append(f"  caption: {s.scene_caption.strip()[:300]}")
        if s.ocr_text.strip():
            lines.append(f"  on-screen: {s.ocr_text.strip()[:300]}")
        if s.speaker_transcript.strip() and s.speaker_transcript != s.transcript:
            lines.append(
                f"  speaker: {s.speaker_transcript.strip()[:400]}"
            )
    return "\n".join(lines)


__all__ = [
    "PROMPT_VERSION",
    "_SYSTEM_PROMPT",
    "_SceneSignals",
    "build_user_prompt",
]