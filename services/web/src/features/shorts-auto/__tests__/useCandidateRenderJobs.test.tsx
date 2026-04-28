import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, waitFor } from "@testing-library/react";

import { useCandidateRenderJobs } from "../hooks/useCandidateRenderJobs";

vi.mock("@/lib/api/shorts-auto", () => ({
  postAutoRender: vi.fn(),
}));
vi.mock("@/lib/api/highlight-reel", async () => {
  return {
    getRenderJobStatus: vi.fn(),
  };
});
vi.mock("@/lib/api/shorts-render", () => ({
  deleteRenderJob: vi.fn(),
  downloadRenderJob: vi.fn(),
}));

import { postAutoRender } from "@/lib/api/shorts-auto";
import { getRenderJobStatus } from "@/lib/api/highlight-reel";
import { deleteRenderJob, downloadRenderJob } from "@/lib/api/shorts-render";

function jobShape(overrides: Partial<{ id: string; status: string; error: string | null }> = {}) {
  return {
    id: overrides.id ?? "j1",
    video_id: "vid",
    title: null,
    status: overrides.status ?? "queued",
    created_at: "",
    completed_at: null,
    render_time_ms: null,
    output_duration_ms: null,
    output_size_bytes: null,
    error: overrides.error ?? null,
    download_url: null,
    thumbnail_video_id: null,
    thumbnail_scene_id: null,
  };
}

function clipShape() {
  return {
    scene_ids: ["vid_scene_000"],
    members: [{ scene_id: "vid_scene_000", start_ms: 0, end_ms: 30_000, score: 0.8 }],
    start_ms: 0,
    end_ms: 30_000,
    duration_ms: 30_000,
    score: 0.8,
    reasons: [],
    is_continuous: true,
  };
}

interface HarnessHandle {
  hook: ReturnType<typeof useCandidateRenderJobs>;
}

// Stable token getter — passing a fresh `async () => "tok"` each render
// would churn the useCallback deps inside the hook. We don't have an
// infinite-loop trigger here (the hook doesn't call the getter on
// render), but using a stable ref is the right pattern and keeps the
// startRender/download/remove identities stable across rerenders.
const stableGetToken = async () => "tok";

function Harness({ onMount }: { onMount: (h: HarnessHandle) => void }) {
  const hook = useCandidateRenderJobs(stableGetToken);
  onMount({ hook });
  return null;
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
});
afterEach(() => {
  vi.useRealTimers();
});

describe("useCandidateRenderJobs", () => {
  it("returns 'candidate' state by default for unknown clips", () => {
    let captured: HarnessHandle | null = null;
    render(<Harness onMount={(h) => (captured = h)} />);
    expect(captured!.hook.getState("anything")).toEqual({ kind: "candidate" });
  });

  it("transitions candidate → submitting → queued on startRender", async () => {
    (postAutoRender as ReturnType<typeof vi.fn>).mockResolvedValue(jobShape({ status: "queued" }));
    let captured: HarnessHandle | null = null;
    const { rerender } = render(<Harness onMount={(h) => (captured = h)} />);

    await act(async () => {
      await captured!.hook.startRender("k1", {
        videoId: "vid",
        mode: "both",
        personClusterId: null,
        title: null,
        clip: clipShape(),
      });
    });
    rerender(<Harness onMount={(h) => (captured = h)} />);
    expect(captured!.hook.getState("k1").kind).toBe("queued");
  });

  it("polls every 5s and lands on completed", async () => {
    (postAutoRender as ReturnType<typeof vi.fn>).mockResolvedValue(jobShape({ status: "queued" }));
    (getRenderJobStatus as ReturnType<typeof vi.fn>)
      .mockResolvedValueOnce(jobShape({ status: "rendering" }))
      .mockResolvedValueOnce(jobShape({ status: "completed" }));

    let captured: HarnessHandle | null = null;
    const { rerender } = render(<Harness onMount={(h) => (captured = h)} />);
    await act(async () => {
      await captured!.hook.startRender("k1", {
        videoId: "vid",
        mode: "both",
        personClusterId: null,
        title: null,
        clip: clipShape(),
      });
    });
    rerender(<Harness onMount={(h) => (captured = h)} />);
    expect(captured!.hook.getState("k1").kind).toBe("queued");

    // tick 1: rendering
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    rerender(<Harness onMount={(h) => (captured = h)} />);
    expect(captured!.hook.getState("k1").kind).toBe("rendering");

    // tick 2: completed
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });
    rerender(<Harness onMount={(h) => (captured = h)} />);
    expect(captured!.hook.getState("k1").kind).toBe("completed");
  });

  it("download is a no-op unless state is completed", async () => {
    let captured: HarnessHandle | null = null;
    render(<Harness onMount={(h) => (captured = h)} />);
    await act(async () => {
      await captured!.hook.download("k1", "x.mp4");
    });
    expect(downloadRenderJob).not.toHaveBeenCalled();
  });

  it("download invokes downloadRenderJob when state is completed", async () => {
    (postAutoRender as ReturnType<typeof vi.fn>).mockResolvedValue(jobShape({ status: "completed" }));
    let captured: HarnessHandle | null = null;
    const { rerender } = render(<Harness onMount={(h) => (captured = h)} />);
    await act(async () => {
      await captured!.hook.startRender("k1", {
        videoId: "vid",
        mode: "both",
        personClusterId: null,
        title: null,
        clip: clipShape(),
      });
    });
    rerender(<Harness onMount={(h) => (captured = h)} />);
    expect(captured!.hook.getState("k1").kind).toBe("completed");

    await act(async () => {
      await captured!.hook.download("k1", "out.mp4");
    });
    expect(downloadRenderJob).toHaveBeenCalledWith("j1", "out.mp4", expect.any(Function));
  });

  it("remove clears local state immediately and DELETEs backend job when present", async () => {
    (postAutoRender as ReturnType<typeof vi.fn>).mockResolvedValue(jobShape({ status: "queued" }));
    let captured: HarnessHandle | null = null;
    const { rerender } = render(<Harness onMount={(h) => (captured = h)} />);
    await act(async () => {
      await captured!.hook.startRender("k1", {
        videoId: "vid",
        mode: "both",
        personClusterId: null,
        title: null,
        clip: clipShape(),
      });
    });

    await act(async () => {
      await captured!.hook.remove("k1");
    });
    rerender(<Harness onMount={(h) => (captured = h)} />);
    expect(captured!.hook.getState("k1")).toEqual({ kind: "candidate" });
    expect(deleteRenderJob).toHaveBeenCalledWith("j1", expect.any(Function));
  });

  it("startRender failure surfaces as failed state", async () => {
    (postAutoRender as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("rate limit"));
    let captured: HarnessHandle | null = null;
    const { rerender } = render(<Harness onMount={(h) => (captured = h)} />);
    await act(async () => {
      await captured!.hook.startRender("k1", {
        videoId: "vid",
        mode: "both",
        personClusterId: null,
        title: null,
        clip: clipShape(),
      });
    });
    rerender(<Harness onMount={(h) => (captured = h)} />);
    const state = captured!.hook.getState("k1");
    expect(state.kind).toBe("failed");
    if (state.kind === "failed") {
      expect(state.error).toBe("rate limit");
    }
  });
});
