/**
 * Map a CompositionSpec font family name → CSS font-family value.
 *
 * `next/font/local` registers each font under a hashed family name and
 * exposes the public CSS variable. Inline styles that use the contract
 * string ("Pretendard", "Noto Sans KR") would otherwise fall back to
 * system-ui because the browser doesn't know about the hashed name.
 *
 * Use this at the inline-style boundary only. Application state still
 * stores the contract string (the API receives "Pretendard", not the
 * CSS variable).
 */
const FONT_FAMILY_CSS_MAP: Record<string, string> = {
  Pretendard: "var(--font-pretendard), 'Pretendard'",
  "Noto Sans KR": "var(--font-noto-kr), 'Noto Sans KR'",
  // 2026-05-18 — declared via @font-face in globals.css with sources
  // pointing at /public/fonts/<NAME>/. The literal family names below
  // match the @font-face declarations exactly.
  "S-Core Dream": "'S-Core Dream', sans-serif",
  NanumSquare: "'NanumSquare', sans-serif",
  SUIT: "'SUIT', sans-serif",
  KoPubWorldDotum: "'KoPubWorldDotum', serif",
};

export function resolveFontFamily(name: string | undefined | null): string {
  if (!name) return "var(--font-pretendard)";
  return FONT_FAMILY_CSS_MAP[name] ?? name;
}
