import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { LoadingShortsProgress } from "../components/LoadingShortsProgress";
import type { JobStatusResponse } from "@/lib/types/shorts-auto-product-wizard";

function makeChild(overrides: Partial<JobStatusResponse> = {}): JobStatusResponse {
  return {
    job_id: "child-1",
    kind: "render_child",
    stage: "queued",
    progress_pct: 0,
    progress_label: null,
    completed_at: null,
    failed_at: null,
    cancelled_at: null,
    error_code: null,
    error_message: null,
    render_job_id: null,
    render_status: "queued",
    parent_job_id: "parent-1",
    shorts_index: 1,
    cost_usd_estimate: "0.00",
    ...overrides,
  };
}

describe("LoadingShortsProgress", () => {
  it("renders bar at 0% when nothing has completed", () => {
    render(
      <LoadingShortsProgress
        children={[makeChild(), makeChild({ job_id: "c2", shorts_index: 2 })]}
        childrenTotal={2}
      />,
    );
    const bar = screen.getByTestId("loading-shorts-progress-bar");
    expect(bar.getAttribute("aria-valuenow")).toBe("0");
    expect(screen.getByText(/쇼츠 0\/2개 준비 중/)).toBeInTheDocument();
  });

  it("fills proportionally to render_status=completed children", () => {
    render(
      <LoadingShortsProgress
        children={[
          makeChild({ render_status: "completed", stage: "done" }),
          makeChild({
            job_id: "c2",
            shorts_index: 2,
            render_status: "rendering",
            stage: "rendering",
          }),
          makeChild({
            job_id: "c3",
            shorts_index: 3,
            render_status: "queued",
            stage: "queued",
          }),
        ]}
        childrenTotal={3}
      />,
    );
    const bar = screen.getByTestId("loading-shorts-progress-bar");
    expect(bar.getAttribute("aria-valuenow")).toBe("33");
    expect(screen.getByText(/쇼츠 1\/3개 준비 중/)).toBeInTheDocument();
  });

  it("shows completion copy when everything is rendered", () => {
    render(
      <LoadingShortsProgress
        children={[
          makeChild({ render_status: "completed", stage: "done" }),
          makeChild({
            job_id: "c2",
            shorts_index: 2,
            render_status: "completed",
            stage: "done",
          }),
        ]}
        childrenTotal={2}
      />,
    );
    expect(
      screen.getByText(/완료! 편집 화면으로 이동합니다…/),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("loading-shorts-progress-bar").getAttribute("aria-valuenow"),
    ).toBe("100");
  });

  it("renders one chip per child in shorts_index order with the right state", () => {
    render(
      <LoadingShortsProgress
        children={[
          makeChild({
            job_id: "c3",
            shorts_index: 3,
            stage: "failed",
            render_status: "failed",
          }),
          makeChild({
            job_id: "c1",
            shorts_index: 1,
            stage: "done",
            render_status: "completed",
          }),
          makeChild({
            job_id: "c2",
            shorts_index: 2,
            stage: "rendering",
            render_status: "rendering",
          }),
        ]}
        childrenTotal={3}
      />,
    );
    const chips = screen.getAllByTestId("loading-shorts-progress-chip");
    expect(chips).toHaveLength(3);
    expect(chips[0].dataset.state).toBe("ready");
    expect(chips[0].textContent).toContain("1");
    expect(chips[0].textContent).toContain("완료");
    expect(chips[1].dataset.state).toBe("working");
    expect(chips[1].textContent).toContain("2");
    expect(chips[1].textContent).toContain("렌더링 중");
    expect(chips[2].dataset.state).toBe("failed");
    expect(chips[2].textContent).toContain("3");
    expect(chips[2].textContent).toContain("실패");
  });

  it("treats queued-render after done-stage as still working", () => {
    // Child stage flips to ``done`` (API enqueued the render) before the
    // render worker picks the job up. We want to show 'rendering' here,
    // not 'completed', because no MP4 exists yet.
    render(
      <LoadingShortsProgress
        children={[
          makeChild({
            stage: "done",
            render_status: "queued",
          }),
        ]}
        childrenTotal={1}
      />,
    );
    const chip = screen.getByTestId("loading-shorts-progress-chip");
    // queued render after a done stage is "queued" (not "ready") — bar
    // is still 0%, not 100%.
    expect(chip.dataset.state).toBe("queued");
    expect(
      screen.getByTestId("loading-shorts-progress-bar").getAttribute("aria-valuenow"),
    ).toBe("0");
  });

  it("shows failed summary line when any child failed", () => {
    render(
      <LoadingShortsProgress
        children={[
          makeChild({
            stage: "done",
            render_status: "completed",
          }),
          makeChild({
            job_id: "c2",
            shorts_index: 2,
            stage: "failed",
            render_status: "failed",
          }),
        ]}
        childrenTotal={2}
      />,
    );
    const summary = screen.getByTestId("loading-shorts-progress-failed");
    expect(summary.textContent).toContain("완료 1");
    expect(summary.textContent).toContain("실패 1");
  });

  it("omits the cancel button when onCancel is not provided", () => {
    render(
      <LoadingShortsProgress children={[makeChild()]} childrenTotal={1} />,
    );
    expect(
      screen.queryByTestId("loading-shorts-progress-cancel"),
    ).not.toBeInTheDocument();
  });

  it("fires onCancel when cancel button clicked", () => {
    const onCancel = vi.fn();
    render(
      <LoadingShortsProgress
        children={[makeChild()]}
        childrenTotal={1}
        onCancel={onCancel}
      />,
    );
    fireEvent.click(screen.getByTestId("loading-shorts-progress-cancel"));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });
});
