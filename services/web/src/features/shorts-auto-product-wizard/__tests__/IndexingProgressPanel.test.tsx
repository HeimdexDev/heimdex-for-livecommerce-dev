import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { IndexingProgressPanel } from "../components/IndexingProgressPanel";
import type { WizardCriteriaDraft } from "../components/InlineWizardCriteriaPanel";

const baseCriteria: WizardCriteriaDraft = {
  length_seconds: 60,
  requested_count: 4,
  time_range_start_ms: 155_000,
  time_range_end_ms: 940_000,
  product_distribution: "single",
};

describe("IndexingProgressPanel", () => {
  it("renders all four stage chips in pipeline order", () => {
    render(
      <IndexingProgressPanel
        criteria={baseCriteria}
        videoDurationMs={940_000}
        progress={0}
        currentStage={null}
      />,
    );
    expect(screen.getByTestId("indexing-stage-enumerating")).toHaveTextContent(
      "분석 중",
    );
    expect(screen.getByTestId("indexing-stage-tracking")).toHaveTextContent(
      "제품 확인",
    );
    expect(screen.getByTestId("indexing-stage-assembling")).toHaveTextContent(
      "분류 중",
    );
    expect(screen.getByTestId("indexing-stage-rendering")).toHaveTextContent(
      "마무리 중",
    );
  });

  it("marks the active stage and rounds the percent", () => {
    render(
      <IndexingProgressPanel
        criteria={baseCriteria}
        videoDurationMs={940_000}
        progress={0.382}
        currentStage="assembling"
        completedStages={["enumerating", "tracking"]}
      />,
    );
    expect(screen.getByTestId("indexing-stage-enumerating").dataset.state).toBe(
      "completed",
    );
    expect(screen.getByTestId("indexing-stage-tracking").dataset.state).toBe(
      "completed",
    );
    expect(screen.getByTestId("indexing-stage-assembling").dataset.state).toBe(
      "active",
    );
    expect(screen.getByTestId("indexing-stage-rendering").dataset.state).toBe(
      "queued",
    );
    expect(screen.getByTestId("indexing-progress-percent")).toHaveTextContent(
      "38%",
    );
  });

  it("hides the ETA when not provided and shows it otherwise", () => {
    const { rerender } = render(
      <IndexingProgressPanel
        criteria={baseCriteria}
        videoDurationMs={940_000}
        progress={0.2}
        currentStage="enumerating"
      />,
    );
    expect(screen.queryByTestId("indexing-progress-eta")).toBeNull();

    rerender(
      <IndexingProgressPanel
        criteria={baseCriteria}
        videoDurationMs={940_000}
        progress={0.2}
        currentStage="enumerating"
        estimatedRemainingSeconds={40}
      />,
    );
    expect(screen.getByTestId("indexing-progress-eta")).toHaveTextContent(
      "약 40초 남았습니다.",
    );
  });

  it("clamps progress out of range", () => {
    const { rerender } = render(
      <IndexingProgressPanel
        criteria={baseCriteria}
        videoDurationMs={940_000}
        progress={-0.5}
        currentStage="enumerating"
      />,
    );
    expect(screen.getByTestId("indexing-progress-percent")).toHaveTextContent(
      "0%",
    );

    rerender(
      <IndexingProgressPanel
        criteria={baseCriteria}
        videoDurationMs={940_000}
        progress={1.4}
        currentStage="rendering"
      />,
    );
    expect(screen.getByTestId("indexing-progress-percent")).toHaveTextContent(
      "100%",
    );
  });

  it("hides the summary chip + 다음 cluster when criteria/videoDurationMs are omitted", () => {
    render(
      <IndexingProgressPanel
        progress={0.5}
        currentStage="tracking"
        completedStages={["enumerating"]}
      />,
    );
    expect(screen.queryByTestId("indexing-summary-chip")).toBeNull();
    expect(screen.getByTestId("indexing-stage-tracking").dataset.state).toBe(
      "active",
    );
    expect(screen.getByTestId("indexing-progress-percent")).toHaveTextContent(
      "50%",
    );
  });

  it("renders the criteria summary chip with distribution + count", () => {
    render(
      <IndexingProgressPanel
        criteria={{ ...baseCriteria, product_distribution: "multi" }}
        videoDurationMs={940_000}
        progress={0.5}
        currentStage="assembling"
      />,
    );
    const chip = screen.getByTestId("indexing-summary-chip");
    expect(chip.textContent).toContain("통합 쇼츠");
    expect(chip.textContent).toContain("60초 길이");
    expect(chip.textContent).toContain("4개 생성");
  });
});
