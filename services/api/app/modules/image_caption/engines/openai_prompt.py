"""Versioned prompt, JSON schema, and banned-term list for OpenAI captioning.

Everything here is an asset, not logic. Bump PROMPT_VERSION on any change,
and the DB column caption_prompt_version (migration 045) lets us target
re-backfill at a specific version if behavior drifts.

LOCKED DECISIONS (ask before changing):
  - PRODUCT_CATEGORIES: 10 entries, aligned with PM for phase 1
  - SEASONS: 5 entries
  - BANNED_PERSON_TERMS: Korean + English substrings — legal/PR sensitive
"""

from __future__ import annotations

from typing import Any

PROMPT_VERSION = "2026-04-13-v1"

PRODUCT_CATEGORIES: list[str] = [
    "스킨케어",
    "색조화장품",
    "건강기능식품",
    "음료",
    "식품",
    "패션",
    "전자제품",
    "생활용품",
    "여행/레저",
    "기타",
]

SEASONS: list[str] = ["봄", "여름", "가을", "겨울", "시즌무관"]

# Case-insensitive substrings. If has_person == true, caption must contain
# NONE of these. The Korean terms were chosen to cover common VMD narration
# leakage (쇼호스트, 모델, 진행자) plus bodily features that imply a person.
# English included as a defense-in-depth in case the model drifts to English.
#
# NOTE: Korean substring matching is whitespace-unaware, so we deliberately
# avoid short terms that collide with common compounds:
#   - "아이" collides with 아이스크림, 아이디어, 아이폰
#   - "손"  collides with 손님, 손잡이, 손상
#   - "팔"  collides with 팔레트, 팔찌
#   - "다리" collides with 다리미 (iron)
#   - "미소" collides with product descriptions
# For each of these we rely on more specific, unambiguous terms instead
# (어린이/아동 for kids; 손가락/손목 for hands; etc.).
BANNED_PERSON_TERMS_KO: list[str] = [
    # Roles
    "쇼호스트", "진행자", "사회자", "호스트", "게스트", "모델",
    # Person nouns
    "여성", "남성", "사람", "인물", "여자", "남자",
    "아동", "어린이", "청년", "노인",
    # Body/appearance features (unambiguous only)
    "얼굴", "머리카락", "손가락", "손목", "손등",
    "표정", "눈빛", "눈동자", "입술",
]

BANNED_PERSON_TERMS_EN: list[str] = [
    "host", "model", "person", "people", "woman", "man",
    "child", "kid", "face", "hand", "smile", "presenter", "mc",
    "girl", "boy", "lady", "gentleman",
]

BANNED_PERSON_TERMS: list[str] = BANNED_PERSON_TERMS_KO + BANNED_PERSON_TERMS_EN


# Structured Outputs schema. strict=True enforces every required field and
# additionalProperties=false, so the parser never has to tolerate missing keys.
JSON_SCHEMA: dict[str, Any] = {
    "name": "vmd_caption",
    "strict": True,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "caption",
            "brand",
            "brand_en",
            "product_category",
            "background_color_ko",
            "dominant_colors_ko",
            "mood",
            "props",
            "season",
            "has_person",
        ],
        "properties": {
            "caption": {
                "type": "string",
                "maxLength": 600,
                "description": (
                    "2~3문장 자연문 묘사. 인물 식별/묘사 금지. "
                    "배경·제품·VMD 구성·색감·소품·분위기만 기술."
                ),
            },
            "brand": {
                "type": ["string", "null"],
                "description": (
                    "이미지에 한글 브랜드명 텍스트가 직접 보일 때만 채움. "
                    "영문 로고만 있으면 null로 두고 brand_en만 채움. "
                    "추측 금지."
                ),
            },
            "brand_en": {
                "type": ["string", "null"],
                "description": "이미지에 영문 로고가 직접 보일 때만. 없으면 null.",
            },
            "product_category": {
                "type": "string",
                "enum": PRODUCT_CATEGORIES,
            },
            "background_color_ko": {
                "type": "string",
                "description": "자연어 한국어. 예: '연한 핑크', '민트에서 흰색 그라데이션'.",
            },
            "dominant_colors_ko": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 4,
                "description": "이미지 전체에서 눈에 띄는 색상 2~4개.",
            },
            "mood": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 2,
                "maxItems": 4,
                "description": "분위기 키워드 2~4개. 예: 로맨틱, 모던, 내추럴, 럭셔리.",
            },
            "props": {
                "type": "array",
                "items": {"type": "string"},
                "minItems": 0,
                "maxItems": 8,
                "description": "대표 소품/장식 0~8개. 구체적으로: '튤립', '하트 쿠션', '유리 구슬'.",
            },
            "season": {
                "type": "string",
                "enum": SEASONS,
                "description": "이미지의 시즌 모티브 기준 (촬영 시점 아님). 시즌성 없으면 '시즌무관'.",
            },
            "has_person": {
                "type": "boolean",
                "description": (
                    "이미지에 사람이나 얼굴이 보이면 true. "
                    "caption 본문에서는 인물을 절대 언급하지 말 것."
                ),
            },
        },
    },
}


SYSTEM_PROMPT = """너는 라이브커머스 VMD(Visual Merchandising Display) 이미지를 검색용 메타데이터로 묘사하는 전문가야.

묘사 규칙:
- caption 필드에는 자연스러운 한국어 서술문 2~3문장 (어색한 필드 나열식 금지)
- 반드시 포함할 정보: 배경 색상, 브랜드명(한글 텍스트가 보일 때만 한글; 영문 로고면 괄호 병기), 제품 카테고리, 진열 구성, 대표 소품/장식, 전체 분위기
- 색상은 "연한 민트", "짙은 보라" 등 구체적으로
- 소품은 "하트 쿠션", "유리 구슬", "튤립" 등 실제로 보이는 것을 구체적으로
- 이미지에 실제로 보이는 요소만 기술 (추측 금지)

인물 처리 (중요):
- 이미지에 사람이나 얼굴이 보여도 절대 인물을 식별·묘사하지 말 것
- 모델·쇼호스트·연예인의 외모·신원·옷차림·표정은 caption에 포함하지 않음
- caption에는 배경·제품·VMD 구성·색감·소품·분위기만 기술
- 사람이 보이면 has_person을 true로만 설정하고, caption 본문에서는 인물 언급 금지
- 인물이라는 단어조차 caption에 포함하지 말 것 (예: "사람", "모델", "여성", "남성", "얼굴", "손" 금지)

구조화 필드 규칙:
- brand는 이미지에 한글 브랜드명 텍스트가 직접 보일 때만. 영문 로고만 있으면 null이고 brand_en만 채움.
- brand_en은 이미지 속 영문 로고가 보일 때만. 없으면 null.
- product_category는 정의된 enum 중에서 선택
- background_color_ko는 자연어 표현 그대로 (예: "민트에서 흰색 그라데이션")
- dominant_colors_ko는 2~4개, 이미지 전체에서 눈에 띄는 색
- mood는 2~4개의 분위기 키워드
- props는 실제로 보이는 대표 소품 0~8개, 구체적으로
- season은 이미지의 시즌 모티브 기준이지 촬영 시점이 아님. 정의된 enum 중에서 선택, 시즌성 없으면 "시즌무관"
- 판단 불가능한 필드는 빈 배열 또는 null로 두고 추측 금지

아래는 스타일·필드 예시야. 이 톤과 구조로 caption과 구조화 필드를 모두 채워줘."""


# Few-shot examples shaped as user/assistant turn pairs so prompt caching
# can reuse the whole prefix across calls. Each user turn is a short
# instruction; each assistant turn is the canonical JSON response.
#
# Images are intentionally omitted from the few-shots (we'd need to ship
# base64-encoded reference images, which bloats every request). The system
# prompt + text-only few-shots are sufficient to lock tone and structure.

FEW_SHOT_TURNS: list[dict[str, Any]] = [
    {
        "role": "user",
        "content": "예시 1: 브링그린 스킨케어 VMD 이미지에 대한 예상 출력을 보여줘.",
    },
    {
        "role": "assistant",
        "content": (
            "{\n"
            '  "caption": "민트에서 흰색으로 이어지는 그라데이션 배경에 브링그린(BRINGGREEN) '
            "스킨케어 제품들이 흰색 천과 테이블 위에 터콰이즈 컬러로 통일되어 배치되어 있다. "
            "열대 잎사귀, 양치식물, 흰 꽃이 곳곳에 놓여 청정 자연 속 보태니컬 가든 같은 "
            '싱그러운 느낌을 준다.",\n'
            '  "brand": "브링그린",\n'
            '  "brand_en": "BRINGGREEN",\n'
            '  "product_category": "스킨케어",\n'
            '  "background_color_ko": "민트에서 흰색 그라데이션",\n'
            '  "dominant_colors_ko": ["민트", "터콰이즈", "화이트"],\n'
            '  "mood": ["싱그러움", "내추럴", "청정"],\n'
            '  "props": ["열대 잎사귀", "양치식물", "흰 꽃", "흰색 천"],\n'
            '  "season": "시즌무관",\n'
            '  "has_person": false\n'
            "}"
        ),
    },
    {
        "role": "user",
        "content": "예시 2: 올세라 이너뷰티 건강기능식품 여름 프로모션 VMD 이미지에 대한 예상 출력을 보여줘.",
    },
    {
        "role": "assistant",
        "content": (
            "{\n"
            '  "caption": "연한 그린에서 노란색으로 이어지는 그라데이션 배경에 짙은 초록색과 '
            "노란색 테이블보, 큐브 디스플레이가 조화롭게 배치되어 있다. 픽셀 아트 스타일의 "
            "'올영세일 LIVE' 로고 아래 이너뷰티 비타민과 건강기능식품들이 진열되어 있으며, "
            "야자수 잎과 노란 아치 장식이 생기 넘치는 여름 웰니스 분위기를 만든다. 그린과 "
            '옐로의 비타민 컬러가 건강하고 에너지 넘치는 이미지를 강조한다.",\n'
            '  "brand": "올세라",\n'
            '  "brand_en": null,\n'
            '  "product_category": "건강기능식품",\n'
            '  "background_color_ko": "연한 그린에서 노란색 그라데이션",\n'
            '  "dominant_colors_ko": ["그린", "옐로", "짙은 초록"],\n'
            '  "mood": ["생기", "에너지", "웰니스"],\n'
            '  "props": ["야자수 잎", "노란 아치", "큐브 디스플레이", "\'올영세일 LIVE\' 로고"],\n'
            '  "season": "여름",\n'
            '  "has_person": false\n'
            "}"
        ),
    },
    {
        "role": "user",
        "content": "예시 3: 배스킨라빈스 우주 테마 프로모션 이미지에 대한 예상 출력을 보여줘.",
    },
    {
        "role": "assistant",
        "content": (
            "{\n"
            '  "caption": "상단 흰색 공간 아래 우주 테마의 화려한 비주얼이 펼쳐진 배스킨라빈스 '
            "프로모션 이미지이다. 우주복 캐릭터와 행성, 은하 배경 위에 아이스크림 컵과 케이크 "
            "제품들이 진열되어 있으며, 보라색과 남색의 우주 컬러가 판타지적인 분위기를 자아낸다. "
            "아이스크림 콘과 케이크 디스플레이가 재미있고 모험적인 브랜드 콘셉트를 "
            '강조한다.",\n'
            '  "brand": "배스킨라빈스",\n'
            '  "brand_en": null,\n'
            '  "product_category": "식품",\n'
            '  "background_color_ko": "상단 흰색, 하단 보라와 남색 우주 배경",\n'
            '  "dominant_colors_ko": ["보라", "남색", "화이트"],\n'
            '  "mood": ["판타지", "모험적", "재미"],\n'
            '  "props": ["우주복 캐릭터", "행성", "은하", "아이스크림 콘", "케이크"],\n'
            '  "season": "시즌무관",\n'
            '  "has_person": false\n'
            "}"
        ),
    },
]


USER_INSTRUCTION = (
    "위 예시와 동일한 스타일·구조로 아래 이미지를 묘사하고 구조화 필드를 채워줘. "
    "JSON 스키마에 맞춰 응답. 인물 식별·묘사 금지."
)
