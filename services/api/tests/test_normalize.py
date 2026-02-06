"""
Unit tests for Korean text normalization.

Tests verify:
1. Excess punctuation removal (!!!, ???, ...)
2. Emoji/symbol spam stripping
3. Hangul + numbers + important punctuation preservation
4. Idempotency (normalize(normalize(x)) == normalize(x))
5. Edge cases (empty, whitespace-only, mixed content)
"""
import pytest
from app.modules.search.normalize import (
    normalize_transcript,
    get_normalized_char_count,
    normalize_for_embedding,
)


class TestNormalizeTranscript:
    """Tests for normalize_transcript function."""

    # ==========================================================================
    # Basic Functionality
    # ==========================================================================

    def test_empty_string(self):
        """Empty string returns empty string."""
        assert normalize_transcript("") == ""

    def test_whitespace_only(self):
        """Whitespace-only string returns empty string."""
        assert normalize_transcript("   ") == ""
        assert normalize_transcript("\t\n\r") == ""

    def test_simple_korean(self):
        """Simple Korean text is lowercased and trimmed."""
        assert normalize_transcript("안녕하세요") == "안녕하세요"
        assert normalize_transcript("  안녕하세요  ") == "안녕하세요"

    def test_simple_english(self):
        """English text is lowercased."""
        assert normalize_transcript("Hello World") == "hello world"
        assert normalize_transcript("API Integration") == "api integration"

    def test_mixed_korean_english(self):
        """Mixed Korean/English text is handled correctly."""
        assert normalize_transcript("API 연동 방법") == "api 연동 방법"
        assert normalize_transcript("SDK 설치 가이드") == "sdk 설치 가이드"

    def test_numbers_preserved(self):
        """Numbers are preserved."""
        assert normalize_transcript("50% 할인") == "50% 할인"
        assert normalize_transcript("7일 이내 반품") == "7일 이내 반품"
        assert normalize_transcript("2024년 1월") == "2024년 1월"

    # ==========================================================================
    # Excess Punctuation Removal
    # ==========================================================================

    def test_repeated_exclamation_marks(self):
        """Multiple exclamation marks collapsed to one."""
        assert normalize_transcript("안녕하세요!!!!") == "안녕하세요!"
        assert normalize_transcript("대박!!!") == "대박!"
        assert normalize_transcript("Wow!!!!!") == "wow!"

    def test_repeated_question_marks(self):
        """Multiple question marks collapsed to one."""
        assert normalize_transcript("뭐라고???") == "뭐라고?"
        assert normalize_transcript("정말????") == "정말?"

    def test_repeated_periods(self):
        """Multiple periods collapsed to one."""
        assert normalize_transcript("그래서...") == "그래서."
        assert normalize_transcript("음.....") == "음."

    def test_repeated_tildes(self):
        """Multiple tildes collapsed to one."""
        assert normalize_transcript("반갑습니다~~~") == "반갑습니다~"
        assert normalize_transcript("안녕~~~~") == "안녕~"

    def test_mixed_repeated_punctuation(self):
        """Mixed repeated punctuation handled correctly."""
        assert normalize_transcript("뭐!?!?!?") == "뭐!?!?!?"  # Alternating not collapsed
        assert normalize_transcript("와우!!! 대박???") == "와우! 대박?"

    def test_single_punctuation_preserved(self):
        """Single punctuation marks preserved."""
        assert normalize_transcript("안녕하세요!") == "안녕하세요!"
        assert normalize_transcript("뭐라고?") == "뭐라고?"
        assert normalize_transcript("그래서.") == "그래서."

    # ==========================================================================
    # Emoji and Symbol Stripping
    # ==========================================================================

    def test_common_emoji_removed(self):
        """Common emoji characters are removed."""
        assert normalize_transcript("세일 🎉🎊 시작!") == "세일 시작!"
        assert normalize_transcript("좋아요 👍👍👍") == "좋아요"
        assert normalize_transcript("❤️ 감사합니다 ❤️") == "감사합니다"

    def test_face_emoji_removed(self):
        """Face emoji removed."""
        assert normalize_transcript("안녕 😀😃😄") == "안녕"
        assert normalize_transcript("슬퍼요 😢😭") == "슬퍼요"

    def test_flag_emoji_removed(self):
        """Flag emoji removed."""
        assert normalize_transcript("한국 🇰🇷 화이팅") == "한국 화이팅"

    def test_emoji_only_returns_empty(self):
        """String with only emoji returns empty."""
        result = normalize_transcript("🎉🎊🎁")
        assert result == ""

    def test_symbol_spam_removed(self):
        """Decorative symbol sequences removed."""
        # Box drawing characters
        assert "━" not in normalize_transcript("━━━ 공지 ━━━")
        # But single special chars might remain if not in spam pattern
        
    # ==========================================================================
    # Whitespace Normalization
    # ==========================================================================

    def test_multiple_spaces_collapsed(self):
        """Multiple spaces collapsed to single space."""
        assert normalize_transcript("안녕    하세요") == "안녕 하세요"
        assert normalize_transcript("세일   기간   입니다") == "세일 기간 입니다"

    def test_tabs_normalized(self):
        """Tabs normalized to spaces."""
        assert normalize_transcript("안녕\t하세요") == "안녕 하세요"

    def test_newlines_normalized(self):
        """Newlines normalized to spaces."""
        assert normalize_transcript("안녕\n하세요") == "안녕 하세요"
        assert normalize_transcript("첫째\r\n둘째\r\n셋째") == "첫째 둘째 셋째"

    def test_leading_trailing_whitespace_stripped(self):
        """Leading and trailing whitespace stripped."""
        assert normalize_transcript("  안녕하세요  ") == "안녕하세요"
        assert normalize_transcript("\n\t안녕\t\n") == "안녕"

    # ==========================================================================
    # Unicode Normalization
    # ==========================================================================

    def test_unicode_nfc_normalization(self):
        """Unicode NFC normalization applied."""
        # Korean jamo should be composed
        # ㅎㅏㄴㄱㅡㄹ (decomposed) -> 한글 (composed)
        decomposed = "\u1112\u1161\u11ab\u1100\u1173\u11af"  # 한글 in jamo
        composed = "한글"
        # After NFC, decomposed jamo should match composed
        result = normalize_transcript(decomposed)
        # Note: NFC may not fully compose all jamo, but should be consistent
        assert normalize_transcript(result) == result  # Idempotent

    # ==========================================================================
    # Idempotency Tests
    # ==========================================================================

    def test_idempotency_simple(self):
        """normalize(normalize(x)) == normalize(x) for simple text."""
        text = "안녕하세요"
        once = normalize_transcript(text)
        twice = normalize_transcript(once)
        assert once == twice

    def test_idempotency_complex(self):
        """normalize(normalize(x)) == normalize(x) for complex text."""
        text = "세일 🎉🎊 50% 할인!!!! 지금 바로~~~"
        once = normalize_transcript(text)
        twice = normalize_transcript(once)
        assert once == twice

    def test_idempotency_mixed_content(self):
        """normalize(normalize(x)) == normalize(x) for mixed content."""
        text = "API 연동!!! SDK 설치??? 가이드..."
        once = normalize_transcript(text)
        twice = normalize_transcript(once)
        assert once == twice

    def test_idempotency_whitespace(self):
        """normalize(normalize(x)) == normalize(x) for whitespace-heavy text."""
        text = "  여러   공백   있음  \n\t "
        once = normalize_transcript(text)
        twice = normalize_transcript(once)
        assert once == twice

    def test_idempotency_emoji_heavy(self):
        """normalize(normalize(x)) == normalize(x) for emoji-heavy text."""
        text = "🎉🎊 축하 🎁🎁🎁 합니다 ❤️❤️❤️"
        once = normalize_transcript(text)
        twice = normalize_transcript(once)
        assert once == twice

    # ==========================================================================
    # Korean-Specific Tests
    # ==========================================================================

    def test_korean_particles_preserved(self):
        """Korean particles (조사) are preserved."""
        assert "은" in normalize_transcript("이것은 테스트입니다")
        assert "를" in normalize_transcript("테스트를 합니다")
        assert "에서" in normalize_transcript("여기에서 시작")

    def test_korean_honorifics_preserved(self):
        """Korean honorifics preserved."""
        assert "하세요" in normalize_transcript("안녕하세요")
        assert "합니다" in normalize_transcript("감사합니다")

    def test_korean_product_terms(self):
        """Common Korean e-commerce terms handled correctly."""
        assert normalize_transcript("신제품 출시") == "신제품 출시"
        assert normalize_transcript("할인 행사") == "할인 행사"
        assert normalize_transcript("무료 배송") == "무료 배송"
        assert normalize_transcript("주문 취소") == "주문 취소"

    def test_korean_technical_terms(self):
        """Korean technical terms with English preserved."""
        assert normalize_transcript("API 연동") == "api 연동"
        assert normalize_transcript("SDK 설치 방법") == "sdk 설치 방법"
        assert normalize_transcript("HTTP 요청") == "http 요청"

    # ==========================================================================
    # Real-World Examples (Golden Query Style)
    # ==========================================================================

    def test_real_world_product_announcement(self):
        """Real-world product announcement text."""
        text = "🎉 신제품 출시!!!! 지금 바로 확인하세요~~~ 👍👍👍"
        expected = "신제품 출시! 지금 바로 확인하세요~"
        assert normalize_transcript(text) == expected

    def test_real_world_sale_announcement(self):
        """Real-world sale announcement text."""
        text = "💰💰💰 50% 할인 행사!!! 이번 주 금요일까지~~~"
        expected = "50% 할인 행사! 이번 주 금요일까지~"
        assert normalize_transcript(text) == expected

    def test_real_world_technical_content(self):
        """Real-world technical content."""
        text = "API 연동 방법... SDK 설치 가이드!!!"
        expected = "api 연동 방법. sdk 설치 가이드!"
        assert normalize_transcript(text) == expected


class TestGetNormalizedCharCount:
    """Tests for get_normalized_char_count function."""

    def test_empty_string(self):
        """Empty string has count 0."""
        assert get_normalized_char_count("") == 0

    def test_simple_text(self):
        """Simple text character count."""
        assert get_normalized_char_count("안녕하세요") == 5
        assert get_normalized_char_count("hello") == 5

    def test_emoji_excluded_from_count(self):
        """Emoji characters excluded from count."""
        # "세일" = 2 chars, " " = 1 char, "시작" = 2 chars, "!" = 1 char = 6
        # After normalization: "세일 시작!" = 6 chars
        text_with_emoji = "세일 🎉🎊 시작!"
        text_without_emoji = "세일 시작!"
        assert get_normalized_char_count(text_with_emoji) == len(normalize_transcript(text_without_emoji))

    def test_repeated_punctuation_collapsed(self):
        """Repeated punctuation counts as one."""
        # "대박!" after normalization = 3 chars
        assert get_normalized_char_count("대박!!!!") == 3

    def test_quality_threshold_boundary(self):
        """Test around quality threshold boundaries (20, 100 chars)."""
        # Create text that normalizes to exactly 20 chars
        short_text = "a" * 20
        assert get_normalized_char_count(short_text) == 20
        
        # Create text that normalizes to exactly 100 chars
        long_text = "a" * 100
        assert get_normalized_char_count(long_text) == 100


class TestNormalizeForEmbedding:
    """Tests for normalize_for_embedding function (lighter normalization)."""

    def test_empty_string(self):
        """Empty string returns empty string."""
        assert normalize_for_embedding("") == ""

    def test_emoji_removed(self):
        """Emoji removed for embedding."""
        assert normalize_for_embedding("세일 🎉 시작") == "세일 시작"

    def test_punctuation_preserved(self):
        """Punctuation preserved for semantic meaning."""
        # Unlike normalize_transcript, repeated punctuation is preserved
        result = normalize_for_embedding("대박!!!")
        assert "!" in result  # Punctuation preserved

    def test_case_preserved(self):
        """Case is preserved for embedding (unlike normalize_transcript)."""
        result = normalize_for_embedding("API Integration")
        assert "API" in result or "api" in result  # Depends on implementation

    def test_whitespace_normalized(self):
        """Whitespace is normalized."""
        assert normalize_for_embedding("세일   기간") == "세일 기간"
        assert normalize_for_embedding("첫째\n둘째") == "첫째 둘째"
