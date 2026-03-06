import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useShortsPlan } from "@/features/videos/hooks/useShortsPlan";
import { generateShortsPlan } from "@/lib/api/shorts";
import { exportToPremiere } from "@/lib/agent-export";
import { exportEdlCloud, exportPremiereCloud } from "@/lib/cloud-export";
import type {
  ShortsCandidateResponse,
  ShortsPlanResponse,
  ExportPremiereResponse,
} from "@/lib/types";
import type { CloudExportResult } from "@/lib/cloud-export";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    getAccessToken: vi.fn().mockResolvedValue("test-token"),
  }),
}));

vi.mock("@/lib/api/shorts", () => ({
  generateShortsPlan: vi.fn(),
}));

vi.mock("@/lib/agent-export", () => ({
  exportToPremiere: vi.fn(),
}));

vi.mock("@/lib/cloud-export", () => ({
  exportEdlCloud: vi.fn(),
  exportPremiereCloud: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const localCandidate: ShortsCandidateResponse = {
  candidate_id: "cand-1",
  video_id: "local-video-1",
  scene_ids: ["scene_0"],
  start_ms: 0,
  end_ms: 30000,
  title_suggestion: "Local Clip",
  reason: "test",
  score: 0.9,
  tags: [],
  product_refs: [],
  people_refs: [],
  transcript_snippet: "transcript",
};

const cloudCandidate: ShortsCandidateResponse = {
  ...localCandidate,
  candidate_id: "cand-2",
  video_id: "gd_cloud-video-1",
  title_suggestion: "Cloud Clip",
};

const planResponse: ShortsPlanResponse = {
  video_id: "local-video-1",
  video_title: "Test Video",
  total_scenes: 10,
  eligible_scenes: 5,
  candidates: [localCandidate],
};

const localExportResult: ExportPremiereResponse = {
  status: "ok",
  format: "edl",
  output_path: "/tmp/test.edl",
  clip_count: 1,
  unresolved_clips: [],
};

const cloudExportResult: CloudExportResult = {
  clip_count: 1,
  unresolved_clips: [],
  filename: "cloud-export.edl",
};

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.mocked(generateShortsPlan).mockReset();
  vi.mocked(exportToPremiere).mockReset();
  vi.mocked(exportEdlCloud).mockReset();
  vi.mocked(exportPremiereCloud).mockReset();
});

describe("useShortsPlan — plan generation", () => {
  it("starts with empty state", () => {
    const { result } = renderHook(() => useShortsPlan());
    expect(result.current.candidates).toEqual([]);
    expect(result.current.isGenerating).toBe(false);
    expect(result.current.planError).toBeNull();
    expect(result.current.selectedIds.size).toBe(0);
  });

  it("generates plan and selects all candidates", async () => {
    vi.mocked(generateShortsPlan).mockResolvedValue(planResponse);

    const { result } = renderHook(() => useShortsPlan());

    await act(async () => {
      await result.current.generatePlan("local-video-1");
    });

    expect(result.current.candidates).toHaveLength(1);
    expect(result.current.totalScenes).toBe(10);
    expect(result.current.eligibleScenes).toBe(5);
    expect(result.current.selectedIds.has("cand-1")).toBe(true);
  });

  it("sets planError on failure", async () => {
    vi.mocked(generateShortsPlan).mockRejectedValue(new Error("Network error"));

    const { result } = renderHook(() => useShortsPlan());

    await act(async () => {
      await result.current.generatePlan("local-video-1");
    });

    expect(result.current.planError).toBe("Failed to generate shorts plan");
    expect(result.current.candidates).toEqual([]);
  });
});

describe("useShortsPlan — selection", () => {
  it("toggleCandidate adds and removes", async () => {
    vi.mocked(generateShortsPlan).mockResolvedValue({
      ...planResponse,
      candidates: [localCandidate, { ...localCandidate, candidate_id: "cand-x" }],
    });

    const { result } = renderHook(() => useShortsPlan());

    await act(async () => {
      await result.current.generatePlan("local-video-1");
    });

    expect(result.current.selectedIds.size).toBe(2);

    act(() => {
      result.current.toggleCandidate("cand-1");
    });
    expect(result.current.selectedIds.has("cand-1")).toBe(false);
    expect(result.current.selectedIds.size).toBe(1);

    act(() => {
      result.current.toggleCandidate("cand-1");
    });
    expect(result.current.selectedIds.has("cand-1")).toBe(true);
  });

  it("deselectAll clears, selectAll restores", async () => {
    vi.mocked(generateShortsPlan).mockResolvedValue(planResponse);

    const { result } = renderHook(() => useShortsPlan());

    await act(async () => {
      await result.current.generatePlan("local-video-1");
    });

    act(() => {
      result.current.deselectAll();
    });
    expect(result.current.selectedIds.size).toBe(0);

    act(() => {
      result.current.selectAll();
    });
    expect(result.current.selectedIds.size).toBe(1);
  });
});

describe("useShortsPlan — export paths", () => {
  const exportConfig = {
    projectName: "Test Project",
    outputDir: "/tmp",
    frameRate: 30,
    agentAvailable: true,
  };

  it("exports local candidates via exportToPremiere", async () => {
    vi.mocked(generateShortsPlan).mockResolvedValue(planResponse);
    vi.mocked(exportToPremiere).mockResolvedValue(localExportResult);

    const { result } = renderHook(() => useShortsPlan());

    await act(async () => {
      await result.current.generatePlan("local-video-1");
    });

    await act(async () => {
      await result.current.exportSelectedToPremiere(exportConfig);
    });

    expect(exportToPremiere).toHaveBeenCalledWith(
      expect.objectContaining({
        project_name: "Test Project",
        frame_rate: 30,
        output_dir: "/tmp",
      }),
    );
    expect(result.current.exportResult?.clip_count).toBe(1);
  });

  it("exports cloud candidates via exportEdlCloud (no mount path)", async () => {
    vi.mocked(generateShortsPlan).mockResolvedValue({
      ...planResponse,
      candidates: [cloudCandidate],
    });
    vi.mocked(exportEdlCloud).mockResolvedValue(cloudExportResult);

    const { result } = renderHook(() => useShortsPlan());

    await act(async () => {
      await result.current.generatePlan("gd_cloud-video-1");
    });

    await act(async () => {
      await result.current.exportSelectedToPremiere(exportConfig);
    });

    expect(exportEdlCloud).toHaveBeenCalled();
    expect(exportToPremiere).not.toHaveBeenCalled();
  });

  it("exports cloud candidates via exportPremiereCloud (with mount path)", async () => {
    vi.mocked(generateShortsPlan).mockResolvedValue({
      ...planResponse,
      candidates: [cloudCandidate],
    });
    vi.mocked(exportPremiereCloud).mockResolvedValue(cloudExportResult);

    const { result } = renderHook(() => useShortsPlan());

    await act(async () => {
      await result.current.generatePlan("gd_cloud-video-1");
    });

    await act(async () => {
      await result.current.exportSelectedToPremiere({
        ...exportConfig,
        driveMountPath: "/Volumes/GoogleDrive",
      });
    });

    expect(exportPremiereCloud).toHaveBeenCalled();
    expect(exportEdlCloud).not.toHaveBeenCalled();
  });

  it("sets exportError on failure", async () => {
    vi.mocked(generateShortsPlan).mockResolvedValue(planResponse);
    vi.mocked(exportToPremiere).mockRejectedValue(new Error("Agent offline"));

    const { result } = renderHook(() => useShortsPlan());

    await act(async () => {
      await result.current.generatePlan("local-video-1");
    });

    await act(async () => {
      await result.current.exportSelectedToPremiere(exportConfig);
    });

    expect(result.current.exportError).toBe("Agent offline");
    expect(result.current.exportResult).toBeNull();
  });

  it("rejects export when nothing selected", async () => {
    vi.mocked(generateShortsPlan).mockResolvedValue(planResponse);

    const { result } = renderHook(() => useShortsPlan());

    await act(async () => {
      await result.current.generatePlan("local-video-1");
    });

    act(() => {
      result.current.deselectAll();
    });

    await act(async () => {
      await result.current.exportSelectedToPremiere(exportConfig);
    });

    expect(result.current.exportError).toBe("Select at least one candidate to export");
  });
});

describe("useShortsPlan — isCloudExport", () => {
  it("returns true when all candidates are cloud videos", async () => {
    vi.mocked(generateShortsPlan).mockResolvedValue({
      ...planResponse,
      candidates: [cloudCandidate],
    });

    const { result } = renderHook(() => useShortsPlan());

    await act(async () => {
      await result.current.generatePlan("gd_cloud-video-1");
    });

    expect(result.current.isCloudExport).toBe(true);
  });

  it("returns false when any candidate is local", async () => {
    vi.mocked(generateShortsPlan).mockResolvedValue({
      ...planResponse,
      candidates: [localCandidate, cloudCandidate],
    });

    const { result } = renderHook(() => useShortsPlan());

    await act(async () => {
      await result.current.generatePlan("local-video-1");
    });

    expect(result.current.isCloudExport).toBe(false);
  });
});

describe("useShortsPlan — reset", () => {
  it("clears all state", async () => {
    vi.mocked(generateShortsPlan).mockResolvedValue(planResponse);

    const { result } = renderHook(() => useShortsPlan());

    await act(async () => {
      await result.current.generatePlan("local-video-1");
    });

    expect(result.current.candidates).toHaveLength(1);

    act(() => {
      result.current.reset();
    });

    expect(result.current.candidates).toEqual([]);
    expect(result.current.isGenerating).toBe(false);
    expect(result.current.planError).toBeNull();
    expect(result.current.totalScenes).toBe(0);
    expect(result.current.eligibleScenes).toBe(0);
    expect(result.current.selectedIds.size).toBe(0);
    expect(result.current.exportResult).toBeNull();
  });
});
