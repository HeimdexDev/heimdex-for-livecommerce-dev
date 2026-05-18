import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import { useContext } from "react";

import {
  InlineWizardCriteriaPanel,
  DEFAULT_CRITERIA,
  type WizardCriteriaDraft,
} from "../components/InlineWizardCriteriaPanel";
import {
  TopHeaderActionsContext,
  TopHeaderActionsProvider,
} from "@/components/layout/TopHeaderActionsContext";

const FIVE_MIN_MS = 300_000;

function HeaderActionsProbe() {
  const ctx = useContext(TopHeaderActionsContext);
  return (
    <div data-testid="header-actions-probe">
      {ctx?.leftActions ?? null}
      {ctx?.actions ?? null}
    </div>
  );
}

function renderPanel(overrides: Partial<WizardCriteriaDraft> = {}) {
  const onCriteriaChange = vi.fn();
  const onNext = vi.fn();
  const utils = render(
    <TopHeaderActionsProvider>
      <InlineWizardCriteriaPanel
        videoId="gd_test"
        videoDurationMs={FIVE_MIN_MS}
        criteria={{ ...DEFAULT_CRITERIA, ...overrides }}
        onCriteriaChange={onCriteriaChange}
        onNext={onNext}
      />
      <HeaderActionsProbe />
    </TopHeaderActionsProvider>,
  );
  return { ...utils, onCriteriaChange, onNext };
}

describe("InlineWizardCriteriaPanel", () => {
  it("renders the breadcrumb at step 1", () => {
    renderPanel();
    expect(
      screen.getByTestId("inline-wizard-breadcrumb"),
    ).toBeInTheDocument();
    expect(
      screen.getByTestId("inline-wizard-breadcrumb-step-1-circle").dataset
        .active,
    ).toBe("true");
  });

  it("renders all four input groups", () => {
    renderPanel();
    expect(screen.getByText("생성 유형")).toBeInTheDocument();
    expect(screen.getByText("영상 구간 설정")).toBeInTheDocument();
    expect(screen.getByText("쇼츠 길이")).toBeInTheDocument();
    expect(screen.getByText("쇼츠 개수")).toBeInTheDocument();
  });

  it("changing the length emits a new criteria object", () => {
    const { onCriteriaChange } = renderPanel();
    fireEvent.click(screen.getByTestId("inline-length-preset-90"));
    expect(onCriteriaChange).toHaveBeenCalledWith({
      ...DEFAULT_CRITERIA,
      length_seconds: 90,
    });
  });

  it("changing the count emits a new criteria object", () => {
    const { onCriteriaChange } = renderPanel();
    fireEvent.click(screen.getByTestId("inline-count-preset-3"));
    expect(onCriteriaChange).toHaveBeenCalledWith({
      ...DEFAULT_CRITERIA,
      requested_count: 3,
    });
  });

  it("changing distribution emits a new criteria object", () => {
    const { onCriteriaChange } = renderPanel();
    fireEvent.click(screen.getByTestId("inline-distribution-multi"));
    expect(onCriteriaChange).toHaveBeenCalledWith({
      ...DEFAULT_CRITERIA,
      product_distribution: "multi",
    });
  });

  it("nudging the slider emits both range fields", () => {
    const { onCriteriaChange } = renderPanel({
      time_range_start_ms: 60_000,
      time_range_end_ms: 240_000,
    });
    fireEvent.keyDown(screen.getByTestId("range-handle-start"), {
      key: "ArrowRight",
    });
    expect(onCriteriaChange).toHaveBeenCalledWith({
      ...DEFAULT_CRITERIA,
      time_range_start_ms: 61_000,
      time_range_end_ms: 240_000,
    });
  });

  it("Next button fires onNext when below aggregate cap", () => {
    const { onNext } = renderPanel();
    fireEvent.click(screen.getByTestId("inline-criteria-next"));
    expect(onNext).toHaveBeenCalledTimes(1);
  });

  it("disables Next + shows warning when length × count > 1800s", () => {
    const { onNext } = renderPanel({
      length_seconds: 120,
      requested_count: 16, // 120 × 16 = 1920 > 1800
    });
    expect(
      screen.getByTestId("inline-aggregate-cap-warning"),
    ).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("inline-criteria-next"));
    expect(onNext).not.toHaveBeenCalled();
  });

  it("smart-count suggestion uses whole video range when range is null", () => {
    renderPanel({
      time_range_start_ms: null,
      time_range_end_ms: null,
      length_seconds: 60,
    });
    // 5 min / 10 min interval → ceil(0.5) = 1 → band [1, 2]
    const suggestion = screen.getByTestId("inline-count-suggestion");
    expect(suggestion.textContent).toContain("1~2개");
  });

  it("smart-count suggestion narrows when user constrains the range", () => {
    renderPanel({
      time_range_start_ms: 60_000,
      time_range_end_ms: 180_000, // 2 min range
      length_seconds: 60,
    });
    // 2 min / 10 min interval → ceil(0.2) = 1 → band [1, 2]
    const suggestion = screen.getByTestId("inline-count-suggestion");
    expect(suggestion.textContent).toContain("1~2개");
  });
});
