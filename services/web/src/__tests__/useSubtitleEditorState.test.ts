/**
 * Vitest coverage for `useSubtitleEditorState` (PR 2 of
 * auto-shorts-subtitle-editor-2026-05-06.md).
 *
 * Real timers + short debounce (10ms). Mirrors the lesson from PR 5
 * of the prior plan: fake timers don't compose with `waitFor`.
 */

import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/lib/api/highlight-reel";
import { useSubtitleEditorState } from "@/features/shorts-auto-product-wizard/hooks/useSubtitleEditorState";

vi.mock("@/lib/api/highlight-reel", async () => {
  const actual = await vi.importActual<typeof api>(
    "@/lib/api/highlight-reel",
  );
  return {
    ...actual,
    patchRenderJobSubtitles: vi.fn(),
  };
});

const RENDER_ID = "00000000-0000-0000-0000-00000000aaaa";
const tokenGetter = () => Promise.resolve("test-token");

const initialCues: api.SubtitleEdit[] = [
  { text: "안녕", start_ms: 0, end_ms: 500 },
  { text: "하세요", start_ms: 500, end_ms: 1000 },
];

function makeRenderResponse(overrides: Partial<api.RenderJobResponse> = {}): api.RenderJobResponse {
  return {
    id: RENDER_ID,
    video_id: "gd_v1",
    title: null,
    status: "completed",
    created_at: "2026-05-06T00:00:00Z",
    completed_at: "2026-05-06T00:01:00Z",
    render_time_ms: 1500,
    output_duration_ms: 1000,
    output_size_bytes: 1024,
    error: null,
    download_url: "https://s3/clip.mp4",
    thumbnail_video_id: null,
    thumbnail_scene_id: null,
    replaced_by_render_job_id: null,
    refined_from_render_job_id: null,
    refinement_source: "manual_edit",
    effective_render_job_id: null,
    summary: null,
    summary_generated_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(api.patchRenderJobSubtitles).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useSubtitleEditorState — initial state", () => {
  it("starts with the supplied cues, idle, no unsaved edits", () => {
    vi.mocked(api.patchRenderJobSubtitles).mockResolvedValue(
      makeRenderResponse(),
    );
    const { result } = renderHook(() =>
      useSubtitleEditorState({
        renderId: RENDER_ID,
        initialCues,
        getToken: tokenGetter,
        debounceMs: 10,
      }),
    );
    expect(result.current.cues).toEqual(initialCues);
    expect(result.current.saveStatus).toBe("idle");
    expect(result.current.hasUnsavedEdits).toBe(false);
    expect(result.current.saveError).toBeNull();
  });
});

describe("useSubtitleEditorState — edit + debounced save", () => {
  it("updateCue sets hasUnsavedEdits and triggers a save after debounce", async () => {
    vi.mocked(api.patchRenderJobSubtitles).mockResolvedValue(
      makeRenderResponse(),
    );
    const { result } = renderHook(() =>
      useSubtitleEditorState({
        renderId: RENDER_ID,
        initialCues,
        getToken: tokenGetter,
        debounceMs: 10,
      }),
    );

    act(() => {
      result.current.updateCue(0, { text: "안녕하세요" });
    });
    expect(result.current.cues[0].text).toBe("안녕하세요");
    expect(result.current.hasUnsavedEdits).toBe(true);

    await waitFor(() => {
      expect(result.current.saveStatus).toBe("saved");
    });
    expect(result.current.hasUnsavedEdits).toBe(false);

    expect(api.patchRenderJobSubtitles).toHaveBeenCalledTimes(1);
    const call = vi.mocked(api.patchRenderJobSubtitles).mock.calls[0];
    expect(call[0]).toBe(RENDER_ID);
    expect(call[1][0].text).toBe("안녕하세요");
    expect(call[1][1].text).toBe("하세요");
  });

  it("coalesces rapid edits into one save call", async () => {
    vi.mocked(api.patchRenderJobSubtitles).mockResolvedValue(
      makeRenderResponse(),
    );
    const { result } = renderHook(() =>
      useSubtitleEditorState({
        renderId: RENDER_ID,
        initialCues,
        getToken: tokenGetter,
        debounceMs: 30,
      }),
    );

    act(() => {
      result.current.updateCue(0, { text: "1" });
      result.current.updateCue(0, { text: "12" });
      result.current.updateCue(0, { text: "123" });
    });

    await waitFor(() => {
      expect(result.current.saveStatus).toBe("saved");
    });

    expect(api.patchRenderJobSubtitles).toHaveBeenCalledTimes(1);
    const sentCues = vi.mocked(api.patchRenderJobSubtitles).mock.calls[0][1];
    // Last edit wins
    expect(sentCues[0].text).toBe("123");
  });

  it("partial updates merge with existing cue", async () => {
    vi.mocked(api.patchRenderJobSubtitles).mockResolvedValue(
      makeRenderResponse(),
    );
    const { result } = renderHook(() =>
      useSubtitleEditorState({
        renderId: RENDER_ID,
        initialCues,
        getToken: tokenGetter,
        debounceMs: 10,
      }),
    );
    act(() => {
      result.current.updateCue(1, { text: "여러분" });
    });
    expect(result.current.cues[1]).toEqual({
      text: "여러분",
      start_ms: 500,
      end_ms: 1000,
    });
  });

  it("ignores out-of-bounds index", () => {
    vi.mocked(api.patchRenderJobSubtitles).mockResolvedValue(
      makeRenderResponse(),
    );
    const { result } = renderHook(() =>
      useSubtitleEditorState({
        renderId: RENDER_ID,
        initialCues,
        getToken: tokenGetter,
        debounceMs: 10,
      }),
    );
    act(() => {
      result.current.updateCue(99, { text: "x" });
    });
    expect(result.current.cues).toEqual(initialCues);
  });
});

describe("useSubtitleEditorState — error path", () => {
  it("surfaces save errors and lets the user retry", async () => {
    vi.mocked(api.patchRenderJobSubtitles)
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValue(makeRenderResponse());

    const { result } = renderHook(() =>
      useSubtitleEditorState({
        renderId: RENDER_ID,
        initialCues,
        getToken: tokenGetter,
        debounceMs: 10,
      }),
    );

    act(() => {
      result.current.updateCue(0, { text: "fail" });
    });

    await waitFor(() => {
      expect(result.current.saveStatus).toBe("error");
    });
    expect(result.current.saveError?.message).toBe("network down");
    expect(result.current.hasUnsavedEdits).toBe(true);

    // Edit again to retry
    act(() => {
      result.current.updateCue(0, { text: "retry" });
    });
    await waitFor(() => {
      expect(result.current.saveStatus).toBe("saved");
    });
  });
});

describe("useSubtitleEditorState — flushNow", () => {
  it("immediately fires save and resolves when done", async () => {
    vi.mocked(api.patchRenderJobSubtitles).mockResolvedValue(
      makeRenderResponse(),
    );
    const { result } = renderHook(() =>
      useSubtitleEditorState({
        renderId: RENDER_ID,
        initialCues,
        getToken: tokenGetter,
        debounceMs: 10_000, // long, would never fire normally
      }),
    );
    act(() => {
      result.current.updateCue(0, { text: "now" });
    });
    expect(result.current.hasUnsavedEdits).toBe(true);
    await act(async () => {
      await result.current.flushNow();
    });
    expect(result.current.saveStatus).toBe("saved");
    expect(api.patchRenderJobSubtitles).toHaveBeenCalledTimes(1);
  });

  it("is a no-op when there are no unsaved edits", async () => {
    vi.mocked(api.patchRenderJobSubtitles).mockResolvedValue(
      makeRenderResponse(),
    );
    const { result } = renderHook(() =>
      useSubtitleEditorState({
        renderId: RENDER_ID,
        initialCues,
        getToken: tokenGetter,
      }),
    );
    await act(async () => {
      await result.current.flushNow();
    });
    expect(api.patchRenderJobSubtitles).not.toHaveBeenCalled();
  });
});

describe("useSubtitleEditorState — renderId pivot", () => {
  it("resets state when renderId changes", () => {
    const { result, rerender } = renderHook(
      ({ id, cues }) =>
        useSubtitleEditorState({
          renderId: id,
          initialCues: cues,
          getToken: tokenGetter,
          debounceMs: 10,
        }),
      { initialProps: { id: RENDER_ID, cues: initialCues } },
    );

    act(() => {
      result.current.updateCue(0, { text: "edit-on-A" });
    });
    expect(result.current.hasUnsavedEdits).toBe(true);

    const newCues: api.SubtitleEdit[] = [{ text: "fresh", start_ms: 0, end_ms: 200 }];
    rerender({ id: "00000000-0000-0000-0000-00000000bbbb", cues: newCues });

    expect(result.current.cues).toEqual(newCues);
    expect(result.current.hasUnsavedEdits).toBe(false);
    expect(result.current.saveStatus).toBe("idle");
  });
});

describe("useSubtitleEditorState — replaceCues", () => {
  it("replaces cues without firing a save", async () => {
    vi.mocked(api.patchRenderJobSubtitles).mockResolvedValue(
      makeRenderResponse(),
    );
    const { result } = renderHook(() =>
      useSubtitleEditorState({
        renderId: RENDER_ID,
        initialCues,
        getToken: tokenGetter,
        debounceMs: 10,
      }),
    );

    const fresh: api.SubtitleEdit[] = [
      { text: "from-server", start_ms: 0, end_ms: 800 },
    ];
    act(() => {
      result.current.replaceCues(fresh);
    });
    expect(result.current.cues).toEqual(fresh);
    expect(result.current.hasUnsavedEdits).toBe(false);
    // Wait long enough that any accidental scheduled save would fire
    await new Promise((r) => setTimeout(r, 50));
    expect(api.patchRenderJobSubtitles).not.toHaveBeenCalled();
  });
});
