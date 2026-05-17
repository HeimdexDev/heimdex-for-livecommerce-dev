import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

const replaceMock = vi.fn();
const useParamsMock = vi.fn();
vi.mock("next/navigation", () => ({
  useParams: () => useParamsMock(),
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ getAccessToken: vi.fn(async () => "test-token") }),
}));

const getRenderJobMock = vi.fn();
vi.mock("@/lib/api/shorts-render", () => ({
  getRenderJob: (...args: unknown[]) => getRenderJobMock(...args),
}));

const editClipsPropsSpy = vi.fn();
vi.mock("next/dynamic", () => ({
  // Stand-in for the real dynamic-imported EditClipsPage. Captures
  // props on every render so we can assert what the route passes
  // through.
  default: () => (props: Record<string, unknown>) => {
    editClipsPropsSpy(props);
    return <div data-testid="edit-clips-stub">edit-clips</div>;
  },
}));

import SavedShortsEditRoute from "../app/export/shorts/[renderJobId]/edit/page";

function makeRender(overrides: Record<string, unknown> = {}) {
  return {
    id: "render-leaf",
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

describe("SavedShortsEditRoute", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    useParamsMock.mockReset();
    getRenderJobMock.mockReset();
    editClipsPropsSpy.mockReset();
  });

  it("mounts EditClipsPage in single mode with the resolved video_id once the render loads", async () => {
    useParamsMock.mockReturnValue({ renderJobId: "render-leaf" });
    getRenderJobMock.mockResolvedValue(makeRender());

    render(<SavedShortsEditRoute />);

    await waitFor(() =>
      expect(screen.getByTestId("edit-clips-stub")).toBeInTheDocument(),
    );

    expect(editClipsPropsSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        mode: "single",
        videoId: "vid-1",
        renderJobId: "render-leaf",
      }),
    );
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("redirects to the leaf URL when the caller hits a stale intermediate", async () => {
    useParamsMock.mockReturnValue({ renderJobId: "render-stale" });
    getRenderJobMock.mockResolvedValue(
      makeRender({
        id: "render-stale",
        effective_render_job_id: "render-leaf-current",
      }),
    );

    render(<SavedShortsEditRoute />);

    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith(
        "/export/shorts/render-leaf-current/edit",
      ),
    );
    // Should NOT have mounted the editor on the stale id.
    expect(editClipsPropsSpy).not.toHaveBeenCalled();
  });

  it("falls back to /export/shorts when the render is not found", async () => {
    useParamsMock.mockReturnValue({ renderJobId: "missing" });
    getRenderJobMock.mockRejectedValue(new Error("Failed to get render job (404)"));

    render(<SavedShortsEditRoute />);

    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith("/export/shorts"),
    );
    expect(editClipsPropsSpy).not.toHaveBeenCalled();
  });

  it("redirects to /export/shorts when the renderJobId param is empty", async () => {
    useParamsMock.mockReturnValue({ renderJobId: "" });

    render(<SavedShortsEditRoute />);

    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith("/export/shorts"),
    );
    expect(getRenderJobMock).not.toHaveBeenCalled();
    expect(editClipsPropsSpy).not.toHaveBeenCalled();
  });

  it("does not mount the editor while the fetch is in flight", () => {
    useParamsMock.mockReturnValue({ renderJobId: "render-leaf" });
    let resolveFn: (value: unknown) => void = () => {};
    getRenderJobMock.mockReturnValue(
      new Promise((resolve) => {
        resolveFn = resolve;
      }),
    );

    render(<SavedShortsEditRoute />);
    expect(screen.getByTestId("saved-shorts-edit-loading")).toBeInTheDocument();
    expect(editClipsPropsSpy).not.toHaveBeenCalled();
    resolveFn(makeRender());
  });
});
