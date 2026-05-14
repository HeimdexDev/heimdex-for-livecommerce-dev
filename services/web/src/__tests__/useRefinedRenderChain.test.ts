/**
 * Vitest coverage for useRefinedRenderChain (PR 5 of whisper-subtitles plan).
 *
 * Mocks `getRenderJobStatus` to drive the polling loop through each
 * lifecycle branch:
 *   - parent_canonical (no refined child appears within grace window)
 *   - refined (child appears, then completes)
 *   - failed (parent fails before refinement is considered)
 *   - timeout (refined child detected but never finishes)
 *   - error (network failure)
 *
 * Uses REAL timers with short intervals (10ms poll, 50-200ms grace/timeout)
 * so `waitFor` from @testing-library can advance them. Fake timers
 * conflict with `waitFor`'s real-time retry loop.
 */

import { renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import * as api from "@/lib/api/highlight-reel";
import { useRefinedRenderChain } from "@/features/shorts-auto-product-wizard/hooks/useRefinedRenderChain";

vi.mock("@/lib/api/highlight-reel", async () => {
  const actual = await vi.importActual<typeof api>(
    "@/lib/api/highlight-reel",
  );
  return {
    ...actual,
    getRenderJobStatus: vi.fn(),
  };
});

const PARENT_ID = "00000000-0000-0000-0000-00000000aaaa";
const CHILD_ID = "00000000-0000-0000-0000-00000000bbbb";

const tokenGetter = () => Promise.resolve("test-token");

function makeJob(overrides: Partial<api.RenderJobResponse> = {}): api.RenderJobResponse {
  return {
    id: PARENT_ID,
    video_id: "gd_v1",
    title: null,
    status: "queued",
    created_at: "2026-05-06T00:00:00Z",
    completed_at: null,
    render_time_ms: null,
    output_duration_ms: null,
    output_size_bytes: null,
    error: null,
    download_url: null,
    thumbnail_video_id: null,
    thumbnail_scene_id: null,
    replaced_by_render_job_id: null,
    refined_from_render_job_id: null,
    refinement_source: null,
    effective_render_job_id: null,
    summary: null,
    summary_generated_at: null,
    ...overrides,
  };
}

beforeEach(() => {
  vi.mocked(api.getRenderJobStatus).mockReset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("useRefinedRenderChain — initial canonical (no refinement)", () => {
  it("settles on the initial render when no refined child appears within grace", async () => {
    vi.mocked(api.getRenderJobStatus).mockResolvedValue(
      makeJob({
        status: "completed",
        completed_at: "2026-05-06T00:01:00Z",
        download_url: "https://s3/parent.mp4",
      }),
    );

    const { result } = renderHook(() =>
      useRefinedRenderChain(PARENT_ID, tokenGetter, {
        pollIntervalMs: 10,
        refinementGraceMs: 50,
        childTimeoutMs: 100,
      }),
    );

    await waitFor(
      () => {
        expect(result.current.stage).toBe("settled_initial_canonical");
      },
      { timeout: 1000 },
    );
    expect(result.current.currentJob?.id).toBe(PARENT_ID);
    expect(result.current.currentJob?.download_url).toBe(
      "https://s3/parent.mp4",
    );
    expect(result.current.isPolling).toBe(false);
  });
});

describe("useRefinedRenderChain — refined child swap", () => {
  it("swaps to the refined child once the parent points at it and the child completes", async () => {
    let childPollCount = 0;
    vi.mocked(api.getRenderJobStatus).mockImplementation(async (id) => {
      if (id === PARENT_ID) {
        return makeJob({
          id: PARENT_ID,
          status: "completed",
          replaced_by_render_job_id: CHILD_ID,
          download_url: "https://s3/parent.mp4",
        });
      }
      childPollCount += 1;
      return makeJob({
        id: CHILD_ID,
        refined_from_render_job_id: PARENT_ID,
        status: childPollCount > 1 ? "completed" : "rendering",
        download_url: childPollCount > 1 ? "https://s3/refined.mp4" : null,
        refinement_source: "whisper",
        effective_render_job_id: null,
      });
    });

    const { result } = renderHook(() =>
      useRefinedRenderChain(PARENT_ID, tokenGetter, {
        pollIntervalMs: 10,
        refinementGraceMs: 5000,
        childTimeoutMs: 5000,
      }),
    );

    await waitFor(
      () => {
        expect(result.current.stage).toBe("settled_refined");
      },
      { timeout: 1000 },
    );
    expect(result.current.currentJob?.id).toBe(CHILD_ID);
    expect(result.current.currentJob?.download_url).toBe(
      "https://s3/refined.mp4",
    );
  });
});

describe("useRefinedRenderChain — failed render", () => {
  it("settles on failure without polling for refinement", async () => {
    vi.mocked(api.getRenderJobStatus).mockResolvedValue(
      makeJob({ status: "failed", error: "render worker died" }),
    );

    const { result } = renderHook(() =>
      useRefinedRenderChain(PARENT_ID, tokenGetter, {
        pollIntervalMs: 10,
      }),
    );

    await waitFor(
      () => {
        expect(result.current.stage).toBe("settled_failed");
      },
      { timeout: 1000 },
    );
    expect(result.current.currentJob?.error).toBe("render worker died");
  });
});

describe("useRefinedRenderChain — disabled / null", () => {
  it("does not poll when initialJobId is null", async () => {
    const { result } = renderHook(() =>
      useRefinedRenderChain(null, tokenGetter),
    );
    expect(api.getRenderJobStatus).not.toHaveBeenCalled();
    expect(result.current.currentJob).toBeNull();
  });

  it("does not poll when enabled=false", async () => {
    renderHook(() =>
      useRefinedRenderChain(PARENT_ID, tokenGetter, { enabled: false }),
    );
    expect(api.getRenderJobStatus).not.toHaveBeenCalled();
  });
});

describe("useRefinedRenderChain — child timeout fallback", () => {
  it("falls back to settled when refined child never completes", async () => {
    vi.mocked(api.getRenderJobStatus).mockImplementation(async (id) => {
      if (id === PARENT_ID) {
        return makeJob({
          id: PARENT_ID,
          status: "completed",
          replaced_by_render_job_id: CHILD_ID,
        });
      }
      return makeJob({
        id: CHILD_ID,
        refined_from_render_job_id: PARENT_ID,
        status: "rendering",
      });
    });

    const { result } = renderHook(() =>
      useRefinedRenderChain(PARENT_ID, tokenGetter, {
        pollIntervalMs: 10,
        refinementGraceMs: 5000,
        childTimeoutMs: 50,
      }),
    );

    await waitFor(
      () => {
        expect(result.current.stage).toBe("settled_initial_canonical");
      },
      { timeout: 1000 },
    );
  });
});

describe("useRefinedRenderChain — fetch error", () => {
  it("surfaces error and stops polling", async () => {
    vi.mocked(api.getRenderJobStatus).mockRejectedValue(
      new Error("network down"),
    );

    const { result } = renderHook(() =>
      useRefinedRenderChain(PARENT_ID, tokenGetter, {
        pollIntervalMs: 10,
      }),
    );

    await waitFor(
      () => {
        expect(result.current.stage).toBe("error");
      },
      { timeout: 1000 },
    );
    expect(result.current.error?.message).toBe("network down");
  });
});

describe("schema mirror", () => {
  it("RenderJobResponse type includes the 3 refinement fields", () => {
    // Compile-time check: if the field is missing from the interface,
    // this assignment fails type-check. Failure shows up at vitest
    // run-time as a TS compile error in the test file.
    const job: api.RenderJobResponse = {
      id: "x",
      video_id: "v",
      title: null,
      status: "queued",
      created_at: "2026-05-06T00:00:00Z",
      completed_at: null,
      render_time_ms: null,
      output_duration_ms: null,
      output_size_bytes: null,
      error: null,
      download_url: null,
      thumbnail_video_id: null,
      thumbnail_scene_id: null,
      replaced_by_render_job_id: null,
      refined_from_render_job_id: null,
      refinement_source: null,
      effective_render_job_id: null,
      summary: null,
      summary_generated_at: null,
    };
    expect(job.replaced_by_render_job_id).toBeNull();
    expect(job.refined_from_render_job_id).toBeNull();
    expect(job.refinement_source).toBeNull();
    expect(job.effective_render_job_id).toBeNull();
  });
});
