import { describe, it, expect } from "vitest";
import { buildCompositionSpec } from "../lib/composition-builder";
import type { EditorState } from "../lib/types";
import { DEFAULT_SUBTITLE_STYLE } from "../constants";

function makeState(overrides: Partial<EditorState> = {}): EditorState {
  return {
    videoId: "gd_test",
    sourceType: "gdrive",
    clips: [],
    subtitles: [],
    overlays: [],
    selectedClipIndex: null,
    selectedSubtitleIndex: null,
    selectedOverlayId: null,
    playheadMs: 0,
    isPlaying: false,
    totalDurationMs: 0,
    zoom: 100,
    isDirty: false,
    ...overrides,
  };
}

describe("buildCompositionSpec", () => {
  it("builds valid spec from single clip", () => {
    const state = makeState({
      clips: [
        {
          id: "c1",
          sceneId: "scene_1",
          videoId: "gd_v1",
          sourceType: "gdrive",
          originalStartMs: 0,
          originalEndMs: 5000,
          trimStartMs: 1000,
          trimEndMs: 4000,
          timelineStartMs: 0,
          volume: 1.5,
        },
      ],
      totalDurationMs: 3000,
    });

    const spec = buildCompositionSpec(state, "My Short");

    expect(spec.version).toBe(1);
    expect(spec.title).toBe("My Short");
    expect(spec.output.width).toBe(406);
    expect(spec.output.height).toBe(720);
    expect(spec.output.fps).toBe(30);
    expect(spec.scene_clips).toHaveLength(1);
    expect(spec.scene_clips[0].scene_id).toBe("scene_1");
    expect(spec.scene_clips[0].start_ms).toBe(1000);
    expect(spec.scene_clips[0].end_ms).toBe(4000);
    expect(spec.scene_clips[0].timeline_start_ms).toBe(0);
    expect(spec.scene_clips[0].volume).toBe(1.5);
    expect(spec.scene_clips[0].crop_w).toBe(1.0);
    expect(spec.subtitles).toHaveLength(0);
    expect(spec.transitions).toHaveLength(0);
  });

  it("builds spec with multiple clips and subtitles", () => {
    const state = makeState({
      clips: [
        {
          id: "c1",
          sceneId: "s1",
          videoId: "v1",
          sourceType: "gdrive",
          originalStartMs: 0,
          originalEndMs: 3000,
          trimStartMs: 0,
          trimEndMs: 3000,
          timelineStartMs: 0,
          volume: 1.0,
        },
        {
          id: "c2",
          sceneId: "s2",
          videoId: "v1",
          sourceType: "gdrive",
          originalStartMs: 5000,
          originalEndMs: 8000,
          trimStartMs: 5000,
          trimEndMs: 8000,
          timelineStartMs: 3000,
          volume: 0.8,
        },
      ],
      subtitles: [
        {
          id: "sub1",
          text: "Hello World",
          startMs: 0,
          endMs: 2000,
          style: { ...DEFAULT_SUBTITLE_STYLE },
        },
      ],
      totalDurationMs: 6000,
    });

    const spec = buildCompositionSpec(state);

    expect(spec.scene_clips).toHaveLength(2);
    expect(spec.scene_clips[1].timeline_start_ms).toBe(3000);
    expect(spec.scene_clips[1].volume).toBe(0.8);
    expect(spec.subtitles).toHaveLength(1);
    expect(spec.subtitles[0].text).toBe("Hello World");
    expect(spec.subtitles[0].style.font_family).toBe("Pretendard");
    expect(spec.subtitles[0].style.font_size_px).toBe(36);
    expect(spec.subtitles[0].style.position_y).toBe(0.85);
    expect(spec.title).toBeNull();
  });

  it("builds empty spec with no clips", () => {
    const state = makeState();
    const spec = buildCompositionSpec(state);

    expect(spec.scene_clips).toHaveLength(0);
    expect(spec.subtitles).toHaveLength(0);
  });

  it("maps subtitle style fields to snake_case", () => {
    const state = makeState({
      clips: [
        {
          id: "c1",
          sceneId: "s1",
          videoId: "v1",
          sourceType: "gdrive",
          originalStartMs: 0,
          originalEndMs: 5000,
          trimStartMs: 0,
          trimEndMs: 5000,
          timelineStartMs: 0,
          volume: 1.0,
        },
      ],
      subtitles: [
        {
          id: "sub1",
          text: "Test",
          startMs: 0,
          endMs: 1000,
          style: {
            fontFamily: "Noto Sans KR",
            fontSizePx: 48,
            fontColor: "#FF0000",
            fontWeight: 400,
            positionX: 0.3,
            positionY: 0.7,
            backgroundColor: "#000000",
            backgroundOpacity: 0.8,
          },
        },
      ],
    });

    const spec = buildCompositionSpec(state);
    const style = spec.subtitles[0].style;

    expect(style.font_family).toBe("Noto Sans KR");
    expect(style.font_size_px).toBe(48);
    expect(style.font_color).toBe("#FF0000");
    expect(style.font_weight).toBe(400);
    expect(style.position_x).toBe(0.3);
    expect(style.position_y).toBe(0.7);
    expect(style.background_color).toBe("#000000");
    expect(style.background_opacity).toBe(0.8);
  });
});
