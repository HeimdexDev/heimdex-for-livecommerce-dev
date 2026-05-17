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
  fontColor: "#FFFFFF",
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

export const FONT_OPTIONS = [
  { value: "Pretendard", label: "Pretendard" },
  { value: "Noto Sans KR", label: "Noto Sans KR" },
] as const;
