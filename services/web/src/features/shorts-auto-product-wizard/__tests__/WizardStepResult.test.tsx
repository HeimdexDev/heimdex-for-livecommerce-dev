import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { WizardStepResult } from "../pages/WizardStepResult";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ getAccessToken: vi.fn(async () => "test-token") }),
}));

// Mock useScanOrder so we feed deterministic status into the page
// without spinning up the real polling loop.
const useScanOrderMock = vi.fn();
vi.mock("../hooks/useScanOrder", () => ({
  useScanOrder: (...args: unknown[]) => useScanOrderMock(...args),
}));

// Mock the shorts-render API so we can assert the right calls without
// hitting the network. Title edit + composition fetch are the two
// surfaces this PR adds.
const updateRenderJobTitleMock = vi.fn();
const getShortCompositionMock = vi.fn();
vi.mock("@/lib/api/shorts-render", () => ({
  updateRenderJobTitle: (...args: unknown[]) =>
    updateRenderJobTitleMock(...args),
  getShortComposition: (...args: unknown[]) =>
    getShortCompositionMock(...args),
}));

const RENDER_ID = "00000000-0000-0000-0000-000000000aaa";

function makeStatus(overrides?: { title?: string | null }) {
  return {
    parent: {
      job_id: "parent-1",
      kind: "scan_order",
      stage: "fanned_out",
      progress_pct: 100,
      progress_label: null,
      completed_at: null,
      failed_at: null,
      cancelled_at: null,
      error_code: null,
      error_message: null,
      render_job_id: null,
      render_status: null,
      parent_job_id: null,
      shorts_index: null,
      cost_usd_estimate: "0.00",
    },
    children: [
      {
        job_id: "child-1",
        kind: "render_child",
        stage: "done",
        progress_pct: 100,
        progress_label: null,
        completed_at: "2026-05-03T12:00:00Z",
        failed_at: null,
        cancelled_at: null,
        error_code: null,
        error_message: null,
        render_job_id: RENDER_ID,
        // v0.16.1 — fixture child has its render finished. WizardStepResult
        // gates the per-card actions (rename, view, edit) on this so the
        // "ready" UX only appears once the MP4 is actually downloadable.
        render_status: "completed",
        parent_job_id: "parent-1",
        shorts_index: 1,
        cost_usd_estimate: "0.00",
      },
    ],
    children_complete: 1,
    children_failed: 0,
    children_total: 1,
    _titleHint: overrides?.title, // not consumed by component, just for clarity
  };
}

describe("WizardStepResult — render actions", () => {
  beforeEach(() => {
    pushMock.mockReset();
    updateRenderJobTitleMock.mockReset();
    getShortCompositionMock.mockReset();
    useScanOrderMock.mockReset();
    useScanOrderMock.mockReturnValue({
      status: makeStatus(),
      error: null,
      isPolling: false,
      cancel: vi.fn(),
    });
  });

  it("renders the title-edit + editor + render-result affordances on completed children", () => {
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(
      screen.getByTestId(`child-title-edit-${RENDER_ID}`),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId(`child-view-render-${RENDER_ID}`),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId(`child-open-editor-${RENDER_ID}`),
    ).toBeInTheDocument();
  });

  it("inline title edit calls updateRenderJobTitle with the trimmed value", async () => {
    updateRenderJobTitleMock.mockResolvedValueOnce({});
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    fireEvent.click(screen.getByTestId(`child-title-edit-${RENDER_ID}`));
    const input = screen.getByTestId(
      `child-title-input-${RENDER_ID}`,
    ) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "  My Cool Short  " } });
    fireEvent.click(screen.getByTestId(`child-title-save-${RENDER_ID}`));

    await waitFor(() =>
      expect(updateRenderJobTitleMock).toHaveBeenCalledWith(
        RENDER_ID,
        "My Cool Short",
        expect.any(Function),
      ),
    );
    // After save, the display reflects the new title.
    await waitFor(() =>
      expect(
        screen.getByTestId(`child-title-display-${RENDER_ID}`).textContent,
      ).toContain("My Cool Short"),
    );
  });

  it("empty title submits null to clear (matches backend semantics)", async () => {
    updateRenderJobTitleMock.mockResolvedValueOnce({});
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    fireEvent.click(screen.getByTestId(`child-title-edit-${RENDER_ID}`));
    fireEvent.change(screen.getByTestId(`child-title-input-${RENDER_ID}`), {
      target: { value: "   " },
    });
    fireEvent.click(screen.getByTestId(`child-title-save-${RENDER_ID}`));
    await waitFor(() =>
      expect(updateRenderJobTitleMock).toHaveBeenCalledWith(
        RENDER_ID,
        null,
        expect.any(Function),
      ),
    );
  });

  it("rolls back the displayed title on save failure", async () => {
    updateRenderJobTitleMock.mockRejectedValueOnce(
      new Error("server says no"),
    );
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    fireEvent.click(screen.getByTestId(`child-title-edit-${RENDER_ID}`));
    fireEvent.change(screen.getByTestId(`child-title-input-${RENDER_ID}`), {
      target: { value: "Fragile Title" },
    });
    fireEvent.click(screen.getByTestId(`child-title-save-${RENDER_ID}`));
    await waitFor(() => expect(updateRenderJobTitleMock).toHaveBeenCalled());
    // Display rolled back to "(제목 없음)" placeholder; the input is closed.
    await waitFor(() =>
      expect(
        screen.queryByTestId(`child-title-input-${RENDER_ID}`),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByTestId(`child-title-display-${RENDER_ID}`).textContent,
    ).toContain("(제목 없음)");
  });

  it("스크립트 편집 routes to inline edit-clips view with the right clip pre-selected", async () => {
    // The fetch is now a permission probe — composition shape doesn't
    // gate the route push (the inline editor loads its own per-clip
    // compositions). What matters: the route + clipIdx query param.
    getShortCompositionMock.mockResolvedValueOnce({
      composition: { scene_clips: [{ scene_id: "gd_test_scene_001" }] },
      source: "render_job",
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    fireEvent.click(screen.getByTestId(`child-open-editor-${RENDER_ID}`));
    await waitFor(() =>
      expect(getShortCompositionMock).toHaveBeenCalledWith(
        RENDER_ID,
        expect.any(Function),
      ),
    );
    await waitFor(() =>
      // Test fixture's child has shorts_index=1, so clipIdx=0.
      expect(pushMock).toHaveBeenCalledWith(
        "/export/shorts/auto/wizard/gd_test/result/parent-1/edit-clips?clipIdx=0",
      ),
    );
  });

  it("surfaces a friendly error if the composition probe 404s", async () => {
    // Permission probe failure (e.g., the render_job belongs to a
    // different user) — the inline editor would fail to populate, so
    // bail early with a Korean message rather than dump the operator
    // on a broken page.
    getShortCompositionMock.mockRejectedValueOnce(
      new Error("Saved short not found"),
    );
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    fireEvent.click(screen.getByTestId(`child-open-editor-${RENDER_ID}`));
    await waitFor(() => expect(getShortCompositionMock).toHaveBeenCalled());
    expect(
      await screen.findByText(/Saved short not found/),
    ).toBeInTheDocument();
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("renders the new 3-step breadcrumb at step 3 (D2)", () => {
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    // The 3-step inline breadcrumb replaces the legacy 4-step WizardLayout
    // breadcrumb. Step 3 is "AI 쇼츠 생성".
    expect(
      screen.getByTestId("inline-wizard-breadcrumb-step-3-circle").dataset
        .active,
    ).toBe("true");
    expect(
      screen.getByTestId("inline-wizard-breadcrumb-step-1-circle").dataset
        .active,
    ).toBe("false");
  });

  it("back link routes to the inline-wizard view on the detail page (D2)", () => {
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    const back = screen.getByTestId("result-back-link");
    expect(back.getAttribute("href")).toBe(
      "/videos/gd_test?view=auto-shorts",
    );
  });
});
