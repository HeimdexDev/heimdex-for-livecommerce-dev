import type { CompositionOutputSpec, SubtitleStyle } from "./lib/types";

export const DEFAULT_OUTPUT: CompositionOutputSpec = {
  width: 406,
  height: 720,
  fps: 30,
  format: "mp4",
  background_color: "#000000",
};

export const DEFAULT_SUBTITLE_STYLE: SubtitleStyle = {
  fontFamily: "Pretendard",
  fontSizePx: 36,
  // Black default — livecommerce frames skew bright so a dark glyph
  // reads better than the previous white default (2026-05-18 review).
  fontColor: "#000000",
  fontWeight: 700,
  positionX: 0.5,
  positionY: 0.85,
  backgroundColor: null,
  backgroundOpacity: 0.6,
};

export const ZOOM_PRESETS = [5, 25, 50, 100, 150, 200, 300] as const;
export const DEFAULT_ZOOM = 100; // px per second
// MIN_ZOOM dropped to 5 so the user can collapse a multi-minute video into
// the visible timeline width — useful for grabbing a coarse overview before
// drilling into a clip. 5 px/sec ≈ 1500px for a 5-minute video.
export const MIN_ZOOM = 5;
export const MAX_ZOOM = 300;

export const DEFAULT_SUBTITLE_DURATION_MS = 3000;
export const MAX_COMPOSITION_DURATION_MS = 300_000; // 5 minutes

// Each option's ``value`` must match a key in FONT_FAMILY_CSS_MAP
// (lib/fonts.ts) AND have a matching next/font/local block in
// app/fonts.ts — otherwise selecting it silently falls back to the
// system default.
export const FONT_OPTIONS = [
  { value: "Pretendard", label: "프리텐다드" },
  { value: "Noto Sans KR", label: "Noto Sans KR" },
  { value: "S-Core Dream", label: "에스코어드림" },
  { value: "NanumSquare", label: "나눔스퀘어" },
  { value: "SUIT", label: "수트(SUIT)" },
  { value: "KoPubWorldDotum", label: "KoPub돋움" },
] as const;
