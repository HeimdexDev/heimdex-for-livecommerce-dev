import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import {
  ExportShortsButton,
  type ExportItemState,
} from "../components/ExportShortsButton";
import type { JobStatusResponse } from "@/lib/types/shorts-auto-product-wizard";

function makeChild(
  jobId: string,
  shortsIndex: number,
  renderJobId: string | null = jobId,
): JobStatusResponse {
  return {
    job_id: jobId,
    kind: "render_child",
    stage: "done",
    progress_pct: 100,
    progress_label: null,
    completed_at: "2026-05-11T00:00:00Z",
    failed_at: null,
    cancelled_at: null,
    error_code: null,
    error_message: null,
    render_job_id: renderJobId,
    render_status: "completed",
    parent_job_id: "parent-1",
    shorts_index: shortsIndex,
    cost_usd_estimate: "0.00",
  };
}

const CHILDREN = [
  makeChild("c1", 1, "render-1"),
  makeChild("c2", 2, "render-2"),
  makeChild("c3", 3, "render-3"),
];

describe("ExportShortsButton — trigger", () => {
  it("renders the trigger label", () => {
    render(
      <ExportShortsButton
        children={CHILDREN}
        activeJobId={null}
        exportState={new Map()}
        onExport={vi.fn()}
      />,
    );
    expect(screen.getByTestId("export-shorts-trigger").textContent).toBe(
      "쇼츠 내보내기",
    );
  });

  it("trigger is disabled when there are no renderable children", () => {
    render(
      <ExportShortsButton
        children={[]}
        activeJobId={null}
        exportState={new Map()}
        onExport={vi.fn()}
      />,
    );
    expect(
      screen.getByTestId("export-shorts-trigger"),
    ).toBeDisabled();
  });

  it("shows progress label while isRunning", () => {
    render(
      <ExportShortsButton
        children={CHILDREN}
        activeJobId={null}
        exportState={new Map()}
        onExport={vi.fn()}
        isRunning
        progressLabel="(1/3)"
      />,
    );
    expect(screen.getByTestId("export-shorts-trigger").textContent).toContain(
      "(1/3)",
    );
  });
});

describe("ExportShortsButton — dropdown", () => {
  beforeEach(() => {
    // jsdom needs cleanup between tests since document-level listeners persist
  });

  it("clicking the trigger opens the dropdown", () => {
    render(
      <ExportShortsButton
        children={CHILDREN}
        activeJobId={null}
        exportState={new Map()}
        onExport={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("export-shorts-trigger"));
    expect(
      screen.getByTestId("export-shorts-dropdown"),
    ).toBeInTheDocument();
  });

  it("pre-selects the active clip on first open", () => {
    render(
      <ExportShortsButton
        children={CHILDREN}
        activeJobId="render-2"
        exportState={new Map()}
        onExport={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("export-shorts-trigger"));
    const c2 = screen.getByTestId("export-shorts-checkbox-2") as HTMLInputElement;
    const c1 = screen.getByTestId("export-shorts-checkbox-1") as HTMLInputElement;
    expect(c2.checked).toBe(true);
    expect(c1.checked).toBe(false);
  });

  it("'모두 내보내기' selects every renderable child", () => {
    render(
      <ExportShortsButton
        children={CHILDREN}
        activeJobId={null}
        exportState={new Map()}
        onExport={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("export-shorts-trigger"));
    fireEvent.click(screen.getByTestId("export-shorts-select-all"));
    expect(
      (screen.getByTestId("export-shorts-checkbox-1") as HTMLInputElement).checked,
    ).toBe(true);
    expect(
      (screen.getByTestId("export-shorts-checkbox-2") as HTMLInputElement).checked,
    ).toBe(true);
    expect(
      (screen.getByTestId("export-shorts-checkbox-3") as HTMLInputElement).checked,
    ).toBe(true);
  });

  it("toggling individual checkbox flips selection state", () => {
    render(
      <ExportShortsButton
        children={CHILDREN}
        activeJobId="render-1"
        exportState={new Map()}
        onExport={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("export-shorts-trigger"));
    fireEvent.click(screen.getByTestId("export-shorts-checkbox-1"));
    expect(
      (screen.getByTestId("export-shorts-checkbox-1") as HTMLInputElement).checked,
    ).toBe(false);
  });

  it("'내보내기' submit fires onExport with the selected ids", () => {
    const onExport = vi.fn();
    render(
      <ExportShortsButton
        children={CHILDREN}
        activeJobId={null}
        exportState={new Map()}
        onExport={onExport}
      />,
    );
    fireEvent.click(screen.getByTestId("export-shorts-trigger"));
    fireEvent.click(screen.getByTestId("export-shorts-checkbox-2"));
    fireEvent.click(screen.getByTestId("export-shorts-checkbox-3"));
    fireEvent.click(screen.getByTestId("export-shorts-submit"));
    expect(onExport).toHaveBeenCalledTimes(1);
    const [arg] = onExport.mock.calls[0];
    expect(arg).toEqual(expect.arrayContaining(["render-2", "render-3"]));
    expect(arg).toHaveLength(2);
  });

  it("submit is disabled when nothing is selected", () => {
    render(
      <ExportShortsButton
        children={CHILDREN}
        activeJobId={null}
        exportState={new Map()}
        onExport={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("export-shorts-trigger"));
    expect(screen.getByTestId("export-shorts-submit")).toBeDisabled();
  });
});

describe("ExportShortsButton — per-row state badge", () => {
  const STATES: Array<[ExportItemState, string]> = [
    [{ status: "queued" }, "export-badge-queued"],
    [{ status: "rendering" }, "export-badge-rendering"],
    [{ status: "completed", downloadUrl: null }, "export-badge-completed"],
    [{ status: "failed", message: "rate-limited" }, "export-badge-failed"],
  ];

  it.each(STATES)("renders the badge for %s", (state, testId) => {
    const exportState = new Map<string, ExportItemState>([
      ["render-1", state],
    ]);
    render(
      <ExportShortsButton
        children={CHILDREN}
        activeJobId="render-1"
        exportState={exportState}
        onExport={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("export-shorts-trigger"));
    expect(screen.getByTestId(testId)).toBeInTheDocument();
  });
});

describe("ExportShortsButton — outside click", () => {
  it("closes the dropdown when clicking outside the container", () => {
    render(
      <div>
        <ExportShortsButton
          children={CHILDREN}
          activeJobId={null}
          exportState={new Map()}
          onExport={vi.fn()}
        />
        <button type="button" data-testid="outside">
          outside
        </button>
      </div>,
    );
    fireEvent.click(screen.getByTestId("export-shorts-trigger"));
    expect(
      screen.getByTestId("export-shorts-dropdown"),
    ).toBeInTheDocument();
    fireEvent.mouseDown(screen.getByTestId("outside"));
    expect(
      screen.queryByTestId("export-shorts-dropdown"),
    ).not.toBeInTheDocument();
  });
});
