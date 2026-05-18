import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { WizardStepResult } from "../pages/WizardStepResult";
import type {
  JobStatusResponse,
  ScanOrderStatusResponse,
  ScanStage,
} from "@/lib/types/shorts-auto-product-wizard";

const replaceMock = vi.fn();
const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: pushMock }),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ getAccessToken: vi.fn(async () => "test-token") }),
}));

const useScanOrderMock = vi.fn();
const cancelMock = vi.fn(async () => {});
vi.mock("../hooks/useScanOrder", () => ({
  useScanOrder: (...args: unknown[]) => useScanOrderMock(...args),
}));

const RENDER_ID_A = "00000000-0000-0000-0000-00000000000a";
const RENDER_ID_B = "00000000-0000-0000-0000-00000000000b";

function makeChild(
  overrides: Partial<JobStatusResponse> = {},
): JobStatusResponse {
  return {
    job_id: "child-1",
    kind: "render_child",
    stage: "done",
    progress_pct: 100,
    progress_label: null,
    completed_at: "2026-05-11T00:00:00Z",
    failed_at: null,
    cancelled_at: null,
    error_code: null,
    error_message: null,
    render_job_id: RENDER_ID_A,
    render_status: "completed",
    parent_job_id: "parent-1",
    // ``shorts_index`` is 1-based on the backend (CHECK shorts_index>=1).
    // Default to 1 here so the slot iterator (which now maps slot i to
    // child with shorts_index === i + 1) finds this child in slot 0.
    shorts_index: 1,
    cost_usd_estimate: "0.00",
    ...overrides,
  };
}

function makeStatus(
  parentStage: ScanStage,
  childrenTotal: number,
  children: JobStatusResponse[],
  childrenFailed = 0,
): ScanOrderStatusResponse {
  return {
    parent: {
      job_id: "parent-1",
      kind: "scan_order",
      stage: parentStage,
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
    children,
    children_complete: children.filter((c) => c.stage === "done").length,
    children_failed: childrenFailed,
    children_total: childrenTotal,
  };
}

beforeEach(() => {
  replaceMock.mockReset();
  pushMock.mockReset();
  cancelMock.mockReset();
  useScanOrderMock.mockReset();
});

describe("WizardStepResult — header", () => {
  it("renders header count from children_total", () => {
    useScanOrderMock.mockReturnValue({
      status: makeStatus("fanned_out", 4, []),
      error: null,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(screen.getByTestId("result-header-count").textContent).toContain("4");
  });

  it("disables 모두 저장/내보내기 when no child has completed render", () => {
    useScanOrderMock.mockReturnValue({
      status: makeStatus("fanned_out", 2, [
        makeChild({ stage: "rendering", render_status: "rendering" }),
      ]),
      error: null,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(screen.getByTestId("result-bulk-save")).toBeDisabled();
    expect(screen.getByTestId("result-bulk-export")).toBeDisabled();
  });

  it("enables 모두 저장/내보내기 once any child has completed render", () => {
    useScanOrderMock.mockReturnValue({
      status: makeStatus("fanned_out", 2, [
        makeChild({
          job_id: "child-a",
          render_job_id: RENDER_ID_A,
          render_status: "completed",
          shorts_index: 1,
        }),
        makeChild({
          job_id: "child-b",
          render_job_id: RENDER_ID_B,
          stage: "rendering",
          render_status: "rendering",
          shorts_index: 2,
          progress_pct: 50,
        }),
      ]),
      error: null,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(screen.getByTestId("result-bulk-save")).not.toBeDisabled();
    expect(screen.getByTestId("result-bulk-export")).not.toBeDisabled();
  });
});

describe("WizardStepResult — grid", () => {
  it("renders one ResultCard per child with 1-based ordinal", () => {
    useScanOrderMock.mockReturnValue({
      status: makeStatus("fanned_out", 2, [
        makeChild({ job_id: "a", shorts_index: 1 }),
        makeChild({ job_id: "b", shorts_index: 2 }),
      ]),
      error: null,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(screen.getByTestId("result-card-1")).toBeInTheDocument();
    expect(screen.getByTestId("result-card-2")).toBeInTheDocument();
  });

  it("shows the empty spinner when fan-out has not landed yet", () => {
    useScanOrderMock.mockReturnValue({
      status: makeStatus("queued", 0, []),
      error: null,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(screen.getByTestId("result-grid-empty")).toBeInTheDocument();
    expect(screen.queryByTestId("result-grid")).not.toBeInTheDocument();
  });

  it("never auto-redirects — the page stays on the grid even when every render is completed", () => {
    useScanOrderMock.mockReturnValue({
      status: makeStatus("committed", 1, [makeChild()]),
      error: null,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(replaceMock).not.toHaveBeenCalled();
    expect(pushMock).not.toHaveBeenCalled();
  });
});

describe("WizardStepResult — status chip mapping", () => {
  const cases: Array<{
    label: string;
    child: Partial<JobStatusResponse>;
    expected: string;
  }> = [
    {
      label: "queued stage → 대기 중",
      child: { stage: "queued", render_status: null, progress_pct: 0 },
      expected: "queued",
    },
    {
      label: "rendering stage → 생성 중",
      child: { stage: "rendering", render_status: "rendering", progress_pct: 40 },
      expected: "working",
    },
    {
      label: "render_status=completed → 완료",
      child: { stage: "done", render_status: "completed", progress_pct: 100 },
      expected: "done",
    },
    {
      label: "failed stage → 실패",
      child: { stage: "failed", render_status: "failed", progress_pct: 0 },
      expected: "failed",
    },
  ];

  for (const c of cases) {
    it(c.label, () => {
      useScanOrderMock.mockReturnValue({
        status: makeStatus("fanned_out", 1, [makeChild(c.child)]),
        error: null,
        cancel: cancelMock,
      });
      render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
      expect(
        screen.getByTestId(`result-status-chip-${c.expected}`),
      ).toBeInTheDocument();
    });
  }
});

describe("WizardStepResult — open editor", () => {
  it("clicking the open-editor icon navigates to the new ShortsEditor route with shortId", () => {
    useScanOrderMock.mockReturnValue({
      status: makeStatus("fanned_out", 1, [makeChild()]),
      error: null,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    fireEvent.click(screen.getByTestId("result-card-open-editor"));
    // 2026-05-18 — route now points at the redesigned ShortsEditorPage
    // which hydrates from ``shortId={render_job_id}``. The legacy
    // ``/edit-clips`` page is only used as a fallback when the child
    // has no render_job_id yet.
    expect(pushMock).toHaveBeenCalledWith(
      `/export/shorts/editor?shortId=${RENDER_ID_A}`,
    );
  });

  it("open-editor icon stays clickable while render is still in progress", () => {
    // 2026-05-18: operators wanted to open the editor even before a
    // child render completes so they can inspect the source clips.
    // The card no longer disables the thumbnail button — it just
    // swaps the aria-label to reflect the in-progress state.
    useScanOrderMock.mockReturnValue({
      status: makeStatus("fanned_out", 1, [
        makeChild({ stage: "rendering", render_status: "rendering" }),
      ]),
      error: null,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    const button = screen.getByTestId("result-card-open-editor");
    expect(button).not.toBeDisabled();
    expect(button).toHaveAttribute(
      "aria-label",
      "쇼츠 생성 중 (편집 페이지 열기)",
    );
  });
});

describe("WizardStepResult — failure & error banners", () => {
  it("renders failure banner when parent stage is failed", () => {
    useScanOrderMock.mockReturnValue({
      status: makeStatus("failed", 1, []),
      error: null,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(screen.getByTestId("wizard-failure-state")).toBeInTheDocument();
  });

  it("renders failure banner with cancelled copy when parent stage is cancelled", () => {
    useScanOrderMock.mockReturnValue({
      status: makeStatus("cancelled", 1, []),
      error: null,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(screen.getByTestId("wizard-failure-state").textContent).toContain(
      "취소되었어요",
    );
  });

  it("surfaces useScanOrder error in the status banner", () => {
    useScanOrderMock.mockReturnValue({
      status: makeStatus("fanned_out", 1, [makeChild()]),
      error: new Error("network blip"),
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(screen.getByTestId("wizard-status-error").textContent).toContain(
      "network blip",
    );
  });
});
