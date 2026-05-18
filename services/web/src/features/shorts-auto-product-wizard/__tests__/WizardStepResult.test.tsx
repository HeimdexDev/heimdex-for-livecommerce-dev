import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

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

const RENDER_ID = "00000000-0000-0000-0000-000000000aaa";

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
    render_job_id: RENDER_ID,
    render_status: "completed",
    parent_job_id: "parent-1",
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

describe("WizardStepResult — chrome", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    pushMock.mockReset();
    cancelMock.mockReset();
    useScanOrderMock.mockReset();
    useScanOrderMock.mockReturnValue({
      status: makeStatus("fanned_out", 3, []),
      error: null,
      isPolling: true,
      cancel: cancelMock,
    });
  });

  it("renders the 2-step breadcrumb at step 2", () => {
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(
      screen.getByTestId("inline-wizard-breadcrumb").dataset.variant,
    ).toBe("two-step");
    expect(
      screen.getByTestId("inline-wizard-breadcrumb-step-2-circle").dataset
        .active,
    ).toBe("true");
    expect(
      screen.queryByTestId("inline-wizard-breadcrumb-step-3-circle"),
    ).not.toBeInTheDocument();
  });

  it("back link points at the inline-wizard view on the detail page", () => {
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(
      screen.getByTestId("result-back-link").getAttribute("href"),
    ).toBe("/videos/gd_test?view=auto-shorts");
  });
});

describe("WizardStepResult — loading state", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    cancelMock.mockReset();
    useScanOrderMock.mockReset();
  });

  it("renders the progress bar + skeleton once fan-out lands (children_total > 0)", () => {
    useScanOrderMock.mockReturnValue({
      status: makeStatus("fanned_out", 3, []),
      error: null,
      isPolling: true,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(screen.getByTestId("wizard-loading-state")).toBeInTheDocument();
    expect(screen.getByTestId("loading-shorts-progress")).toBeInTheDocument();
    expect(
      screen.queryByTestId("loading-shorts-spinner"),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByTestId("loading-shorts-skeleton-card"),
    ).toHaveLength(3);
  });

  it("renders the indeterminate spinner before fan-out (children_total = 0)", () => {
    useScanOrderMock.mockReturnValue({
      status: makeStatus("queued", 0, []),
      error: null,
      isPolling: true,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(screen.getByTestId("wizard-loading-state")).toBeInTheDocument();
    expect(screen.getByTestId("loading-shorts-spinner")).toBeInTheDocument();
    expect(
      screen.queryByTestId("loading-shorts-progress"),
    ).not.toBeInTheDocument();
  });

  it("cancel button calls useScanOrder.cancel() (progress mode)", async () => {
    useScanOrderMock.mockReturnValue({
      status: makeStatus("fanned_out", 2, []),
      error: null,
      isPolling: true,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    fireEvent.click(screen.getByTestId("loading-shorts-progress-cancel"));
    await waitFor(() => expect(cancelMock).toHaveBeenCalledTimes(1));
  });

  it("cancel button calls useScanOrder.cancel() (spinner mode, pre-fan-out)", async () => {
    useScanOrderMock.mockReturnValue({
      status: makeStatus("queued", 0, []),
      error: null,
      isPolling: true,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    fireEvent.click(screen.getByTestId("loading-shorts-spinner-cancel"));
    await waitFor(() => expect(cancelMock).toHaveBeenCalledTimes(1));
  });

  it("renders skeleton header with 0 when status hasn't loaded yet", () => {
    useScanOrderMock.mockReturnValue({
      status: null,
      error: null,
      isPolling: true,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(screen.getByTestId("wizard-loading-state")).toBeInTheDocument();
    expect(
      screen.queryAllByTestId("loading-shorts-skeleton-card"),
    ).toHaveLength(0);
  });

  it("surfaces a polling error inline", () => {
    useScanOrderMock.mockReturnValue({
      status: null,
      error: new Error("network down"),
      isPolling: false,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(screen.getByTestId("wizard-status-error").textContent).toContain(
      "network down",
    );
  });
});

describe("WizardStepResult — auto-redirect", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    cancelMock.mockReset();
    useScanOrderMock.mockReset();
  });

  it("redirects to /edit-clips when parent terminal AND first child render completed", async () => {
    useScanOrderMock.mockReturnValue({
      status: makeStatus("done", 2, [
        makeChild({ render_status: "completed" }),
        makeChild({ job_id: "child-2", shorts_index: 2 }),
      ]),
      error: null,
      isPolling: false,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith(
        "/export/shorts/auto/wizard/gd_test/result/parent-1/edit-clips",
      ),
    );
  });

  it("redirects as soon as ≥1 child render completes even while parent fanned_out", async () => {
    // 1-of-3 success: one render landed, two siblings still in flight.
    // Old predicate stalled here because parent.stage="fanned_out".
    useScanOrderMock.mockReturnValue({
      status: makeStatus("fanned_out", 3, [
        makeChild({ render_status: "completed" }),
        makeChild({
          job_id: "child-2",
          shorts_index: 2,
          stage: "rendering",
          render_status: "rendering",
          completed_at: null,
        }),
        makeChild({
          job_id: "child-3",
          shorts_index: 3,
          stage: "rendering",
          render_status: "queued",
          completed_at: null,
        }),
      ]),
      error: null,
      isPolling: true,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith(
        "/export/shorts/auto/wizard/gd_test/result/parent-1/edit-clips",
      ),
    );
  });

  it("redirects when one child completes and another already failed", async () => {
    useScanOrderMock.mockReturnValue({
      status: makeStatus(
        "fanned_out",
        2,
        [
          makeChild({ render_status: "completed" }),
          makeChild({
            job_id: "child-2",
            shorts_index: 2,
            stage: "failed",
            render_status: "failed",
            completed_at: null,
            failed_at: "2026-05-12T00:00:00Z",
          }),
        ],
        1,
      ),
      error: null,
      isPolling: true,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith(
        "/export/shorts/auto/wizard/gd_test/result/parent-1/edit-clips",
      ),
    );
  });

  it("does NOT redirect while no render has produced an MP4 yet", () => {
    useScanOrderMock.mockReturnValue({
      status: makeStatus("fanned_out", 1, [
        makeChild({
          stage: "rendering",
          render_status: "rendering",
          completed_at: null,
        }),
      ]),
      error: null,
      isPolling: true,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(replaceMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("wizard-loading-state")).toBeInTheDocument();
  });

  it("does NOT redirect on parent failed", () => {
    useScanOrderMock.mockReturnValue({
      status: makeStatus("failed", 1, [
        makeChild({ render_status: "completed" }),
      ]),
      error: null,
      isPolling: false,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(replaceMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("wizard-failure-state")).toBeInTheDocument();
  });

  it("does NOT redirect on parent cancelled", () => {
    useScanOrderMock.mockReturnValue({
      status: makeStatus("cancelled", 1, [
        makeChild({ render_status: "completed" }),
      ]),
      error: null,
      isPolling: false,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(replaceMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("wizard-failure-state")).toBeInTheDocument();
  });

  it("does NOT redirect when all children failed (treats whole-batch failure as failure)", () => {
    useScanOrderMock.mockReturnValue({
      status: makeStatus(
        "done",
        2,
        [
          makeChild({ stage: "failed", render_status: "failed" }),
          makeChild({
            job_id: "child-2",
            shorts_index: 2,
            stage: "failed",
            render_status: "failed",
          }),
        ],
        2, // children_failed
      ),
      error: null,
      isPolling: false,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(replaceMock).not.toHaveBeenCalled();
    expect(screen.getByTestId("wizard-failure-state")).toBeInTheDocument();
  });

  it("redirect fires at most once even if status reference changes", async () => {
    const status = makeStatus("done", 1, [
      makeChild({ render_status: "completed" }),
    ]);
    useScanOrderMock.mockReturnValue({
      status,
      error: null,
      isPolling: false,
      cancel: cancelMock,
    });
    const { rerender } = render(
      <WizardStepResult videoId="gd_test" parentJobId="parent-1" />,
    );
    await waitFor(() => expect(replaceMock).toHaveBeenCalledTimes(1));
    // Force a re-render with a different status object reference but the
    // same redirect-trigger predicate — useEffect would re-run, but the ref
    // guard should keep replace at exactly 1 call.
    useScanOrderMock.mockReturnValue({
      status: makeStatus("done", 1, [
        makeChild({ render_status: "completed" }),
      ]),
      error: null,
      isPolling: false,
      cancel: cancelMock,
    });
    rerender(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(replaceMock).toHaveBeenCalledTimes(1);
  });
});

describe("WizardStepResult — failure state", () => {
  beforeEach(() => {
    replaceMock.mockReset();
    cancelMock.mockReset();
    useScanOrderMock.mockReset();
  });

  it("renders friendlyParentError when parent has an error_code", () => {
    useScanOrderMock.mockReturnValue({
      status: {
        ...makeStatus("failed", 0, []),
        parent: {
          ...makeStatus("failed", 0, []).parent,
          error_code: "proxy_missing",
          error_message: "file_id=foo not transcoded",
        },
      },
      error: null,
      isPolling: false,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    const failure = screen.getByTestId("wizard-failure-state");
    expect(failure.textContent).toContain("트랜스코딩이 완료되지 않았어요");
  });

  it("renders a generic message on parent cancelled with no error_code", () => {
    useScanOrderMock.mockReturnValue({
      status: makeStatus("cancelled", 0, []),
      error: null,
      isPolling: false,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(
      screen.getByTestId("wizard-failure-state").textContent,
    ).toContain("취소되었어요");
  });

  // ─────────────────────────────────────────────────────────────────
  // No-render failure: every child completed via
  // ``_complete_no_render`` (stage=done, render_status≠"completed").
  // Covers the STT pipeline's friendly-failure reasons:
  // ``stt_no_mentions``, ``stt_transcript_unavailable``, and the
  // Phase-1 ``stt_live_block_too_short``. Pre-fix, the user stared
  // at the loading spinner forever.
  // ─────────────────────────────────────────────────────────────────

  it("surfaces the no-render Korean message when a single child completed with no render", () => {
    const child = makeChild({
      stage: "done",
      render_job_id: null,
      render_status: null,
    });
    useScanOrderMock.mockReturnValue({
      status: makeStatus("committed", 1, [child]),
      error: null,
      isPolling: false,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    const failure = screen.getByTestId("wizard-failure-state");
    expect(failure.textContent).toContain(
      "쇼츠를 만들 수 있는 구간을 찾지 못했어요",
    );
    // Should NOT incorrectly redirect — there's no MP4 to view.
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("surfaces the no-render Korean message when ALL children of a multi-product wizard completed with no render", () => {
    const child1 = makeChild({
      job_id: "child-1",
      shorts_index: 1,
      stage: "done",
      render_job_id: null,
      render_status: null,
    });
    const child2 = makeChild({
      job_id: "child-2",
      shorts_index: 2,
      stage: "done",
      render_job_id: null,
      render_status: null,
    });
    const child3 = makeChild({
      job_id: "child-3",
      shorts_index: 3,
      stage: "done",
      render_job_id: null,
      render_status: null,
    });
    useScanOrderMock.mockReturnValue({
      status: makeStatus("committed", 3, [child1, child2, child3]),
      error: null,
      isPolling: false,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    expect(
      screen.getByTestId("wizard-failure-state").textContent,
    ).toContain("쇼츠를 만들 수 있는 구간을 찾지 못했어요");
  });

  it("does NOT surface the no-render message when one child produced a render and others did not", async () => {
    // Mixed: one success, one no-render. The success path wins —
    // user gets redirected to /edit-clips, not the failure state.
    const success = makeChild({
      job_id: "child-1",
      shorts_index: 1,
      stage: "done",
      render_job_id: RENDER_ID,
      render_status: "completed",
    });
    const noRender = makeChild({
      job_id: "child-2",
      shorts_index: 2,
      stage: "done",
      render_job_id: null,
      render_status: null,
    });
    useScanOrderMock.mockReturnValue({
      status: makeStatus("committed", 2, [success, noRender]),
      error: null,
      isPolling: false,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    await waitFor(() => expect(replaceMock).toHaveBeenCalled());
    expect(
      screen.queryByTestId("wizard-failure-state"),
    ).not.toBeInTheDocument();
  });

  it("does NOT surface the no-render message while a child is still running", () => {
    // ``deriveState`` requires all children terminal before flipping
    // to failure — otherwise we'd race the in-flight scan job and
    // surface a premature error.
    const done = makeChild({
      job_id: "child-1",
      shorts_index: 1,
      stage: "done",
      render_job_id: null,
      render_status: null,
    });
    const running = makeChild({
      job_id: "child-2",
      shorts_index: 2,
      stage: "rendering",
      render_job_id: null,
      render_status: null,
    });
    useScanOrderMock.mockReturnValue({
      status: makeStatus("fanned_out", 2, [done, running]),
      error: null,
      isPolling: true,
      cancel: cancelMock,
    });
    render(<WizardStepResult videoId="gd_test" parentJobId="parent-1" />);
    // Stays in loading state — failure UI must NOT appear yet.
    expect(
      screen.queryByTestId("wizard-failure-state"),
    ).not.toBeInTheDocument();
    expect(
      screen.getByTestId("wizard-loading-state"),
    ).toBeInTheDocument();
  });
});
