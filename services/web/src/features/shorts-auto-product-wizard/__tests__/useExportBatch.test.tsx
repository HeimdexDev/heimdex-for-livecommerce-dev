import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, renderHook } from "@testing-library/react";

import { useExportBatch } from "../hooks/useExportBatch";

const rerenderFromEditsMock = vi.fn();
const getRenderJobMock = vi.fn();

vi.mock("@/lib/api/highlight-reel", () => ({
  rerenderFromEdits: (...args: unknown[]) => rerenderFromEditsMock(...args),
}));

vi.mock("@/lib/api/shorts-render", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/api/shorts-render")
  >("@/lib/api/shorts-render");
  return {
    ...actual,
    getRenderJob: (...args: unknown[]) => getRenderJobMock(...args),
  };
});

const getToken = vi.fn(async () => "test-token");

function makeRender(
  id: string,
  status: "queued" | "rendering" | "completed" | "failed" = "completed",
  download_url: string | null = "https://download/" + id,
  error: string | null = null,
) {
  return {
    id,
    video_id: "vid",
    title: null,
    status,
    created_at: "2026-05-11T00:00:00Z",
    completed_at: null,
    render_time_ms: null,
    output_duration_ms: null,
    output_size_bytes: null,
    error,
    download_url,
    thumbnail_video_id: null,
    thumbnail_scene_id: null,
    replaced_by_render_job_id: null,
    refined_from_render_job_id: null,
    refinement_source: null,
  };
}

describe("useExportBatch", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    rerenderFromEditsMock.mockReset();
    getRenderJobMock.mockReset();
    getToken.mockClear();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("is a no-op when called with an empty jobIds list", async () => {
    const { result } = renderHook(() =>
      useExportBatch(getToken, { pollIntervalMs: 10, perClipTimeoutMs: 200 }),
    );
    await act(async () => {
      await result.current.start([]);
    });
    expect(rerenderFromEditsMock).not.toHaveBeenCalled();
    expect(result.current.isRunning).toBe(false);
    expect(result.current.state.size).toBe(0);
  });

  it("renders sequentially and exposes per-clip terminal state", async () => {
    rerenderFromEditsMock
      .mockResolvedValueOnce(makeRender("child-1", "queued"))
      .mockResolvedValueOnce(makeRender("child-2", "queued"));
    getRenderJobMock
      .mockResolvedValueOnce(makeRender("child-1", "completed"))
      .mockResolvedValueOnce(makeRender("child-2", "completed"));

    const { result } = renderHook(() =>
      useExportBatch(getToken, { pollIntervalMs: 10, perClipTimeoutMs: 200 }),
    );

    await act(async () => {
      const promise = result.current.start(["parent-1", "parent-2"]);
      // Advance through both clips' polls
      await vi.advanceTimersByTimeAsync(50);
      await promise;
    });

    expect(rerenderFromEditsMock).toHaveBeenCalledTimes(2);
    expect(rerenderFromEditsMock).toHaveBeenNthCalledWith(
      1,
      "parent-1",
      expect.any(Function),
    );
    expect(rerenderFromEditsMock).toHaveBeenNthCalledWith(
      2,
      "parent-2",
      expect.any(Function),
    );
    const final1 = result.current.state.get("parent-1");
    const final2 = result.current.state.get("parent-2");
    expect(final1?.status).toBe("completed");
    if (final1?.status === "completed") {
      expect(final1.downloadUrl).toBe("https://download/child-1");
    }
    expect(final2?.status).toBe("completed");
    expect(result.current.isRunning).toBe(false);
  });

  it("rate-limit error on one clip does NOT abort the batch", async () => {
    const { RenderRateLimitError } = await vi.importActual<
      typeof import("@/lib/api/shorts-render")
    >("@/lib/api/shorts-render");

    rerenderFromEditsMock
      .mockRejectedValueOnce(new RenderRateLimitError("too many"))
      .mockResolvedValueOnce(makeRender("child-2", "queued"));
    getRenderJobMock.mockResolvedValueOnce(makeRender("child-2", "completed"));

    const { result } = renderHook(() =>
      useExportBatch(getToken, { pollIntervalMs: 10, perClipTimeoutMs: 200 }),
    );
    await act(async () => {
      const promise = result.current.start(["parent-1", "parent-2"]);
      await vi.advanceTimersByTimeAsync(50);
      await promise;
    });

    expect(rerenderFromEditsMock).toHaveBeenCalledTimes(2);
    const s1 = result.current.state.get("parent-1");
    const s2 = result.current.state.get("parent-2");
    expect(s1?.status).toBe("failed");
    if (s1?.status === "failed") {
      expect(s1.message).toContain("잠시 후");
    }
    expect(s2?.status).toBe("completed");
  });

  it("generic error message surfaces in failed state without aborting", async () => {
    rerenderFromEditsMock
      .mockRejectedValueOnce(new Error("backend boom"))
      .mockResolvedValueOnce(makeRender("child-2", "queued"));
    getRenderJobMock.mockResolvedValueOnce(makeRender("child-2", "completed"));

    const { result } = renderHook(() =>
      useExportBatch(getToken, { pollIntervalMs: 10, perClipTimeoutMs: 200 }),
    );
    await act(async () => {
      const promise = result.current.start(["parent-1", "parent-2"]);
      await vi.advanceTimersByTimeAsync(50);
      await promise;
    });

    const s1 = result.current.state.get("parent-1");
    expect(s1?.status).toBe("failed");
    if (s1?.status === "failed") {
      expect(s1.message).toBe("backend boom");
    }
    const s2 = result.current.state.get("parent-2");
    expect(s2?.status).toBe("completed");
  });

  it("polling timeout surfaces as failure with 시간 초과", async () => {
    rerenderFromEditsMock.mockResolvedValueOnce(
      makeRender("child-1", "queued"),
    );
    // Always return non-terminal so we hit timeout
    getRenderJobMock.mockResolvedValue(makeRender("child-1", "rendering"));

    const { result } = renderHook(() =>
      useExportBatch(getToken, { pollIntervalMs: 10, perClipTimeoutMs: 30 }),
    );
    await act(async () => {
      const promise = result.current.start(["parent-1"]);
      await vi.advanceTimersByTimeAsync(100);
      await promise;
    });

    const s = result.current.state.get("parent-1");
    expect(s?.status).toBe("failed");
    if (s?.status === "failed") {
      expect(s.message).toBe("시간 초과");
    }
  });

  it("backend-reported failure surfaces as failed with the error message", async () => {
    rerenderFromEditsMock.mockResolvedValueOnce(
      makeRender("child-1", "queued"),
    );
    getRenderJobMock.mockResolvedValueOnce(
      makeRender("child-1", "failed", null, "ffmpeg crashed"),
    );

    const { result } = renderHook(() =>
      useExportBatch(getToken, { pollIntervalMs: 10, perClipTimeoutMs: 200 }),
    );
    await act(async () => {
      const promise = result.current.start(["parent-1"]);
      await vi.advanceTimersByTimeAsync(50);
      await promise;
    });

    const s = result.current.state.get("parent-1");
    expect(s?.status).toBe("failed");
    if (s?.status === "failed") {
      expect(s.message).toBe("ffmpeg crashed");
    }
  });
});
