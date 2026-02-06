"""
Korean text normalization for search quality.

This module provides transcript normalization functions to:
- Improve Korean search recall through consistent text forms
- Remove noise (emoji, excessive punctuation, symbols)
- Maintain a reversible link between raw and normalized text

The normalization is designed to be:
- Idempotent: normalize(normalize(x)) == normalize(x)
- Preserving: Korean text meaning is maintained
- Consistent: Same input always produces same output
"""
import re
import unicodedata


# Regex patterns compiled once for performance
# Match sequences of 2+ repeated punctuation (!!!, ???, ..., ~~~)
_REPEATED_PUNCT_PATTERN = re.compile(r'([!?.,~\-=+]{2,})')

# Match emoji and pictographic characters (Unicode ranges)
# This covers most common emoji including:
# - Emoticons (1F600-1F64F)
# - Dingbats (2700-27BF)
# - Transport/Map symbols (1F680-1F6FF)
# - Misc symbols (2600-26FF)
# - Supplemental symbols (1F900-1F9FF)
# - Symbols and pictographs extended-A (1FA00-1FA6F)
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # Emoticons
    "\U0001F300-\U0001F5FF"  # Misc symbols and pictographs
    "\U0001F680-\U0001F6FF"  # Transport and map
    "\U0001F700-\U0001F77F"  # Alchemical symbols
    "\U0001F780-\U0001F7FF"  # Geometric shapes extended
    "\U0001F800-\U0001F8FF"  # Supplemental arrows-C
    "\U0001F900-\U0001F9FF"  # Supplemental symbols and pictographs
    "\U0001FA00-\U0001FA6F"  # Chess symbols, extended-A
    "\U0001FA70-\U0001FAFF"  # Symbols and pictographs extended-A
    "\U00002702-\U000027B0"  # Dingbats
    "\U00002600-\U000026FF"  # Misc symbols
    "\U0000FE00-\U0000FE0F"  # Variation selectors
    "\U0001F1E0-\U0001F1FF"  # Flags (iOS)
    "]+",
    flags=re.UNICODE
)

# Match symbol spam (sequences of decorative characters)
# Covers: stars, hearts, music notes, arrows, box drawing, etc.
_SYMBOL_SPAM_PATTERN = re.compile(
    r'[\u2500-\u257F'   # Box drawing
    r'\u2580-\u259F'    # Block elements
    r'\u25A0-\u25FF'    # Geometric shapes
    r'\u2190-\u21FF'    # Arrows
    r'\u2B00-\u2BFF'    # Misc symbols and arrows
    r'\u3000'           # Ideographic space
    r'\uFF01-\uFF5E'    # Fullwidth ASCII variants (except useful ones)
    r']{2,}'            # 2+ in sequence = spam
)

# Match excessive whitespace (3+ spaces, mixed tabs/spaces)
_EXCESSIVE_WHITESPACE_PATTERN = re.compile(r'[ \t]{3,}')

# Match newlines and normalize to single space
_NEWLINE_PATTERN = re.compile(r'[\r\n]+')


def normalize_transcript(text: str) -> str:
    """
    Normalize transcript text for improved search quality.
    
    This function applies the following transformations:
    1. Unicode NFC normalization (canonical composition)
    2. Remove emoji and pictographic characters
    3. Collapse repeated punctuation (!!!! -> !)
    4. Remove symbol spam (decorative characters)
    5. Normalize whitespace (collapse, trim)
    6. Lowercase for case-insensitive matching
    
    The function is idempotent: normalize(normalize(x)) == normalize(x)
    
    Args:
        text: Raw transcript text (may contain Korean, English, numbers, punctuation)
        
    Returns:
        Normalized text suitable for search indexing
        
    Examples:
        >>> normalize_transcript("안녕하세요!!!! 반갑습니다~~~")
        '안녕하세요! 반갑습니다~'
        
        >>> normalize_transcript("세일 기간 🎉🎊 50% 할인!")
        '세일 기간 50% 할인!'
        
        >>> normalize_transcript("API 연동 방법")
        'api 연동 방법'
    """
    if not text:
        return ""
    
    # Step 1: Unicode NFC normalization
    # Ensures consistent representation of Korean jamo combinations
    text = unicodedata.normalize("NFC", text)
    
    # Step 2: Remove emoji and pictographic characters
    text = _EMOJI_PATTERN.sub("", text)
    
    # Step 3: Collapse repeated punctuation (!!!! -> !, ??? -> ?, ~~~ -> ~)
    text = re.sub(r'([!?.,~\-=+])\1+', r'\1', text)
    
    # Step 4: Remove symbol spam (decorative characters)
    text = _SYMBOL_SPAM_PATTERN.sub(" ", text)
    
    # Step 5: Normalize newlines and tabs to space
    text = _NEWLINE_PATTERN.sub(" ", text)
    text = text.replace("\t", " ")
    
    # Step 6: Normalize excessive whitespace
    text = _EXCESSIVE_WHITESPACE_PATTERN.sub(" ", text)
    
    # Step 7: Lowercase
    text = text.lower()
    
    # Step 8: Strip leading/trailing whitespace
    text = text.strip()
    
    # Step 9: Final whitespace normalization (collapse any remaining multiple spaces)
    text = re.sub(r' +', ' ', text)
    
    return text


def get_normalized_char_count(text: str) -> int:
    """
    Get character count of normalized text for quality scoring.
    
    This provides a more accurate quality signal than raw character count
    by excluding emoji, excessive punctuation, and other noise.
    
    Args:
        text: Raw or normalized transcript text
        
    Returns:
        Character count of the normalized text
    """
    normalized = normalize_transcript(text)
    return len(normalized)


def normalize_for_embedding(text: str) -> str:
    """
    Light normalization for embedding input.
    
    Less aggressive than normalize_transcript() to preserve semantic content
    while still removing obvious noise.
    
    Args:
        text: Raw transcript text
        
    Returns:
        Lightly normalized text for embedding model input
    """
    if not text:
        return ""
    
    # Unicode NFC normalization
    text = unicodedata.normalize("NFC", text)
    
    # Remove emoji only (preserve punctuation for semantic meaning)
    text = _EMOJI_PATTERN.sub("", text)
    
    # Normalize whitespace
    text = _NEWLINE_PATTERN.sub(" ", text)
    text = re.sub(r' +', ' ', text)
    text = text.strip()
    
    return text
