import { describe, it, expect } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useEditorState, createClipFromScene } from "../hooks/useEditorState";
import type { EditorClip } from "../lib/types";

function makeClip(overrides: Partial<EditorClip> = {}): EditorClip {
  return {
    id: `clip_${Math.random()}`,
    sceneId: "scene_1",
    videoId: "gd_video1",
    sourceType: "gdrive",
    originalStartMs: 0,
    originalEndMs: 5000,
    trimStartMs: 0,
    trimEndMs: 5000,
    timelineStartMs: 0,
    volume: 1.0,
    ...overrides,
  };
}

describe("useEditorState", () => {
  it("initializes with empty state", () => {
    const { result } = renderHook(() => useEditorState());
    expect(result.current.state.clips).toHaveLength(0);
    expect(result.current.state.isDirty).toBe(false);
  });

  it("INIT_FROM_SCENES sets clips and computes timeline", () => {
    const { result } = renderHook(() => useEditorState());
    const clip1 = makeClip({ id: "c1", originalStartMs: 0, originalEndMs: 3000, trimStartMs: 0, trimEndMs: 3000 });
    const clip2 = makeClip({ id: "c2", originalStartMs: 10000, originalEndMs: 15000, trimStartMs: 10000, trimEndMs: 15000 });

    act(() => result.current.initFromScenes("vid1", "gdrive", [clip1, clip2]));

    expect(result.current.state.clips).toHaveLength(2);
    expect(result.current.state.clips[0].timelineStartMs).toBe(0);
    expect(result.current.state.clips[1].timelineStartMs).toBe(3000);
    expect(result.current.state.totalDurationMs).toBe(8000);
    expect(result.current.state.videoId).toBe("vid1");
    expect(result.current.state.isDirty).toBe(false);
  });

  it("ADD_CLIP appends and recomputes timeline", () => {
    const { result } = renderHook(() => useEditorState());
    const clip1 = makeClip({ id: "c1", trimStartMs: 0, trimEndMs: 2000 });

    act(() => result.current.initFromScenes("v", "gdrive", [clip1]));
    act(() => result.current.addClip(makeClip({ id: "c2", trimStartMs: 5000, trimEndMs: 8000 })));

    expect(result.current.state.clips).toHaveLength(2);
    expect(result.current.state.clips[1].timelineStartMs).toBe(2000);
    expect(result.current.state.totalDurationMs).toBe(5000);
    expect(result.current.state.isDirty).toBe(true);
  });

  it("REMOVE_CLIP removes and recomputes", () => {
    const { result } = renderHook(() => useEditorState());
    const clips = [
      makeClip({ id: "c1", trimStartMs: 0, trimEndMs: 2000 }),
      makeClip({ id: "c2", trimStartMs: 0, trimEndMs: 3000 }),
    ];

    act(() => result.current.initFromScenes("v", "gdrive", clips));
    act(() => result.current.removeClip(0));

    expect(result.current.state.clips).toHaveLength(1);
    expect(result.current.state.clips[0].id).toBe("c2");
    expect(result.current.state.clips[0].timelineStartMs).toBe(0);
    expect(result.current.state.totalDurationMs).toBe(3000);
  });

  it("REMOVE_CLIP adjusts selectedClipIndex when removing before selected", () => {
    const { result } = renderHook(() => useEditorState());
    const clips = [
      makeClip({ id: "a", trimStartMs: 0, trimEndMs: 1000 }),
      makeClip({ id: "b", trimStartMs: 0, trimEndMs: 2000 }),
      makeClip({ id: "c", trimStartMs: 0, trimEndMs: 3000 }),
    ];
    act(() => result.current.initFromScenes("v", "gdrive", clips));
    act(() => result.current.selectClip(2)); // select "c"
    act(() => result.current.removeClip(0)); // remove "a"

    // "c" was at index 2, now should be at index 1
    expect(result.current.state.selectedClipIndex).toBe(1);
    expect(result.current.state.clips[1].id).toBe("c");
  });

  it("REMOVE_SUBTITLE adjusts selectedSubtitleIndex when removing before selected", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    const sub = (id: string) => ({
      id,
      text: id,
      startMs: 0,
      endMs: 1000,
      style: {
        fontFamily: "Pretendard",
        fontSizePx: 36,
        fontColor: "#FFFFFF",
        fontWeight: 700,
        positionX: 0.5,
        positionY: 0.85,
        backgroundColor: null,
        backgroundOpacity: 0.6,
      },
    });
    act(() => result.current.addSubtitle(sub("s1")));
    act(() => result.current.addSubtitle(sub("s2")));
    act(() => result.current.addSubtitle(sub("s3")));
    act(() => result.current.selectSubtitle(2)); // select "s3"
    act(() => result.current.removeSubtitle(0)); // remove "s1"

    expect(result.current.state.selectedSubtitleIndex).toBe(1);
    expect(result.current.state.subtitles[1].id).toBe("s3");
  });

  it("REMOVE_CLIP ignores out of range", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    act(() => result.current.removeClip(5));
    expect(result.current.state.clips).toHaveLength(1);
  });

  it("REORDER_CLIPS swaps and recomputes", () => {
    const { result } = renderHook(() => useEditorState());
    const clips = [
      makeClip({ id: "c1", trimStartMs: 0, trimEndMs: 2000 }),
      makeClip({ id: "c2", trimStartMs: 0, trimEndMs: 5000 }),
    ];

    act(() => result.current.initFromScenes("v", "gdrive", clips));
    act(() => result.current.reorderClips(0, 1));

    expect(result.current.state.clips[0].id).toBe("c2");
    expect(result.current.state.clips[1].id).toBe("c1");
    expect(result.current.state.clips[0].timelineStartMs).toBe(0);
    expect(result.current.state.clips[1].timelineStartMs).toBe(5000);
    expect(result.current.state.selectedClipIndex).toBe(1);
  });

  it("REORDER_CLIPS ignores same index", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip({ id: "c1" })]));
    act(() => result.current.reorderClips(0, 0));
    expect(result.current.state.isDirty).toBe(false);
  });

  it("TRIM_CLIP clamps within scene bounds", () => {
    const { result } = renderHook(() => useEditorState());
    const clip = makeClip({
      id: "c1",
      originalStartMs: 1000,
      originalEndMs: 6000,
      trimStartMs: 1000,
      trimEndMs: 6000,
    });

    act(() => result.current.initFromScenes("v", "gdrive", [clip]));

    // Try to trim start before original start
    act(() => result.current.trimClip(0, 500, undefined));
    expect(result.current.state.clips[0].trimStartMs).toBe(1000);

    // Try to trim end past original end
    act(() => result.current.trimClip(0, undefined, 9000));
    expect(result.current.state.clips[0].trimEndMs).toBe(6000);

    // Valid trim
    act(() => result.current.trimClip(0, 2000, 4000));
    expect(result.current.state.clips[0].trimStartMs).toBe(2000);
    expect(result.current.state.clips[0].trimEndMs).toBe(4000);
    expect(result.current.state.totalDurationMs).toBe(2000);
  });

  it("TRIM_CLIP ensures start < end", () => {
    const { result } = renderHook(() => useEditorState());
    const clip = makeClip({
      id: "c1",
      originalStartMs: 0,
      originalEndMs: 5000,
      trimStartMs: 0,
      trimEndMs: 5000,
    });

    act(() => result.current.initFromScenes("v", "gdrive", [clip]));
    // Try to set start past current end
    act(() => result.current.trimClip(0, 6000, undefined));
    expect(result.current.state.clips[0].trimStartMs).toBeLessThan(
      result.current.state.clips[0].trimEndMs,
    );
  });

  it("SET_CLIP_VOLUME clamps to 0-3", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip({ id: "c1" })]));

    act(() => result.current.setClipVolume(0, 5.0));
    expect(result.current.state.clips[0].volume).toBe(3);

    act(() => result.current.setClipVolume(0, -1));
    expect(result.current.state.clips[0].volume).toBe(0);

    act(() => result.current.setClipVolume(0, 1.5));
    expect(result.current.state.clips[0].volume).toBe(1.5);
  });

  it("SELECT_CLIP deselects subtitle", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    act(() => result.current.selectSubtitle(0));
    act(() => result.current.selectClip(0));
    expect(result.current.state.selectedClipIndex).toBe(0);
    expect(result.current.state.selectedSubtitleIndex).toBeNull();
  });

  it("subtitle CRUD works", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));

    const sub = {
      id: "sub1",
      text: "Hello",
      startMs: 0,
      endMs: 2000,
      style: {
        fontFamily: "Pretendard",
        fontSizePx: 36,
        fontColor: "#FFFFFF",
        fontWeight: 700,
        positionX: 0.5,
        positionY: 0.85,
        backgroundColor: null,
        backgroundOpacity: 0.6,
      },
    };

    act(() => result.current.addSubtitle(sub));
    expect(result.current.state.subtitles).toHaveLength(1);

    act(() => result.current.updateSubtitle(0, { text: "Updated" }));
    expect(result.current.state.subtitles[0].text).toBe("Updated");

    act(() => result.current.removeSubtitle(0));
    expect(result.current.state.subtitles).toHaveLength(0);
  });

  it("SET_ZOOM clamps to 25-300", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.setZoom(10));
    expect(result.current.state.zoom).toBe(25);
    act(() => result.current.setZoom(500));
    expect(result.current.state.zoom).toBe(300);
  });

  it("addOverlayAtPlayhead creates an empty overlay at the playhead and selects it", () => {
    const { result } = renderHook(() => useEditorState());
    act(() =>
      result.current.initFromScenes("v", "gdrive", [
        makeClip({ id: "c1", trimStartMs: 0, trimEndMs: 10_000 }),
      ]),
    );
    act(() => result.current.setPlayhead(2000));

    expect(result.current.state.subtitles).toHaveLength(0);

    act(() => result.current.addOverlayAtPlayhead());

    expect(result.current.state.subtitles).toHaveLength(1);
    const sub = result.current.state.subtitles[0];
    expect(sub.text).toBe("");
    expect(sub.startMs).toBe(2000);
    expect(sub.endMs).toBeGreaterThan(sub.startMs);
    expect(result.current.state.selectedSubtitleIndex).toBe(0);
    expect(result.current.state.isDirty).toBe(true);
  });

  it("addOverlayAtPlayhead clamps end_ms to total duration", () => {
    const { result } = renderHook(() => useEditorState());
    act(() =>
      result.current.initFromScenes("v", "gdrive", [
        makeClip({ id: "c1", trimStartMs: 0, trimEndMs: 4_000 }),
      ]),
    );
    act(() => result.current.setPlayhead(3500));

    act(() => result.current.addOverlayAtPlayhead());

    const sub = result.current.state.subtitles[0];
    expect(sub.endMs).toBeLessThanOrEqual(result.current.state.totalDurationMs);
  });

  it("MARK_CLEAN resets isDirty", () => {
    const { result } = renderHook(() => useEditorState());
    act(() => result.current.initFromScenes("v", "gdrive", [makeClip()]));
    act(() => result.current.addClip(makeClip({ id: "c2" })));
    expect(result.current.state.isDirty).toBe(true);
    act(() => result.current.markClean());
    expect(result.current.state.isDirty).toBe(false);
  });
});

describe("createClipFromScene", () => {
  it("creates a clip from a scene object", () => {
    const scene = { scene_id: "s1", start_ms: 1000, end_ms: 4000 };
    const clip = createClipFromScene(scene, "gd_video", "gdrive");

    expect(clip.sceneId).toBe("s1");
    expect(clip.videoId).toBe("gd_video");
    expect(clip.originalStartMs).toBe(1000);
    expect(clip.originalEndMs).toBe(4000);
    expect(clip.trimStartMs).toBe(1000);
    expect(clip.trimEndMs).toBe(4000);
    expect(clip.volume).toBe(1.0);
    expect(clip.id).toBeTruthy();
  });
});
