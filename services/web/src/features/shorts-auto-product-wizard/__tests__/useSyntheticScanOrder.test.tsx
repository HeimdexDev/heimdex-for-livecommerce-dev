import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";

import { useSyntheticScanOrder } from "../hooks/useSyntheticScanOrder";

const getRenderJobMock = vi.fn();
vi.mock("@/lib/api/shorts-render", () => ({
  getRenderJob: (...args: unknown[]) => getRenderJobMock(...args),
}));

const tokenGetter = vi.fn(async () => "test-token");

function makeRender(overrides: Record<string, unknown> = {}) {
  return {
    id: "render-1",
    video_id: "vid-1",
    title: "Test Short",
    status: "completed",
    created_at: "2026-05-13T00:00:00Z",
    completed_at: "2026-05-13T00:01:00Z",
    render_time_ms: 60000,
    output_duration_ms: 30000,
    output_size_bytes: 1024,
    error: null,
    download_url: "https://s3/clip.mp4",
    thumbnail_video_id: "vid-1",
    thumbnail_scene_id: "vid-1_scene_001",
    replaced_by_render_job_id: null,
    refined_from_render_job_id: null,
    refinement_source: null,
    effective_render_job_id: null,
    summary: null,
    summary_generated_at: null,
    ...overrides,
  };
}

describe("useSyntheticScanOrder", () => {
  beforeEach(() => {
    getRenderJobMock.mockReset();
    tokenGetter.mockReset();
  });

  it("returns null status while the render fetch is in flight", () => {
    let resolveFn: (value: unknown) => void = () => {};
    getRenderJobMock.mockReturnValue(
      new Promise((resolve) => {
        resolveFn = resolve;
      }),
    );

    const { result } = renderHook(() =>
      useSyntheticScanOrder("render-1", tokenGetter),
    );

    expect(result.current.status).toBeNull();
    expect(result.current.error).toBeNull();
    expect(result.current.isPolling).toBe(true);
    // unblock so the test doesn't leak the pending promise
    resolveFn(makeRender());
  });

  it("returns a one-child ScanOrderStatusResponse after fetch resolves", async () => {
    getRenderJobMock.mockResolvedValue(makeRender({ status: "completed" }));

    const { result } = renderHook(() =>
      useSyntheticScanOrder("render-1", tokenGetter),
    );

    await waitFor(() => expect(result.current.status).not.toBeNull());

    const status = result.current.status!;
    expect(status.parent.stage).toBe("committed");
    expect(status.children_total).toBe(1);
    expect(status.children).toHaveLength(1);
    expect(status.children[0].render_job_id).toBe("render-1");
    expect(status.children[0].render_status).toBe("completed");
    expect(status.children[0].stage).toBe("done");
    expect(status.children[0].shorts_index).toBe(1);
    expect(status.children_complete).toBe(1);
    expect(status.children_failed).toBe(0);
  });

  it("maps a rendering job to in-flight stage", async () => {
    getRenderJobMock.mockResolvedValue(makeRender({ status: "rendering" }));

    const { result } = renderHook(() =>
      useSyntheticScanOrder("render-1", tokenGetter),
    );
    await waitFor(() => expect(result.current.status).not.toBeNull());

    expect(result.current.status!.children[0].stage).toBe("rendering");
    expect(result.current.status!.children_complete).toBe(0);
    expect(result.current.status!.children_failed).toBe(0);
  });

  it("counts a failed render in children_failed", async () => {
    getRenderJobMock.mockResolvedValue(makeRender({ status: "failed" }));

    const { result } = renderHook(() =>
      useSyntheticScanOrder("render-1", tokenGetter),
    );
    await waitFor(() => expect(result.current.status).not.toBeNull());

    expect(result.current.status!.children[0].stage).toBe("failed");
    expect(result.current.status!.children_complete).toBe(0);
    expect(result.current.status!.children_failed).toBe(1);
  });

  it("surfaces fetch errors instead of returning a stale status", async () => {
    getRenderJobMock.mockRejectedValue(new Error("network down"));

    const { result } = renderHook(() =>
      useSyntheticScanOrder("render-1", tokenGetter),
    );
    await waitFor(() => expect(result.current.error).not.toBeNull());

    expect(result.current.status).toBeNull();
    expect(result.current.error?.message).toBe("network down");
    expect(result.current.isPolling).toBe(false);
  });

  it("treats a null renderJobId as inactive (no fetch fired)", () => {
    renderHook(() => useSyntheticScanOrder(null, tokenGetter));
    expect(getRenderJobMock).not.toHaveBeenCalled();
  });

  it("exposes a no-op cancel callable for parity with useScanOrder", async () => {
    getRenderJobMock.mockResolvedValue(makeRender());
    const { result } = renderHook(() =>
      useSyntheticScanOrder("render-1", tokenGetter),
    );
    await waitFor(() => expect(result.current.status).not.toBeNull());
    await expect(result.current.cancel()).resolves.toBeUndefined();
  });
});
