import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { InlineLengthSelector } from "../components/InlineLengthSelector";
import {
  InlineCountSelector,
  computeSmartCountSuggestion,
} from "../components/InlineCountSelector";
import { InlineDistributionToggle } from "../components/InlineDistributionToggle";

describe("InlineLengthSelector", () => {
  it("renders 5 presets, no custom input", () => {
    render(<InlineLengthSelector value={60} onChange={vi.fn()} />);
    [15, 30, 60, 90, 120].forEach((p) =>
      expect(screen.getByTestId(`inline-length-preset-${p}`)).toBeInTheDocument(),
    );
    expect(screen.queryByTestId("length-custom-input")).not.toBeInTheDocument();
  });

  it("marks the active preset and fires onChange", () => {
    const onChange = vi.fn();
    render(<InlineLengthSelector value={30} onChange={onChange} />);
    expect(
      screen.getByTestId("inline-length-preset-30").dataset.active,
    ).toBe("true");
    expect(
      screen.getByTestId("inline-length-preset-60").dataset.active,
    ).toBe("false");
    fireEvent.click(screen.getByTestId("inline-length-preset-90"));
    expect(onChange).toHaveBeenCalledWith(90);
  });
});

describe("computeSmartCountSuggestion", () => {
  it("returns null for non-positive range or length", () => {
    expect(computeSmartCountSuggestion(0, 60)).toBeNull();
    expect(computeSmartCountSuggestion(60_000, 0)).toBeNull();
    expect(computeSmartCountSuggestion(-1, 60)).toBeNull();
  });

  it("returns the band [n-1, n+1] around ceil(range / length)", () => {
    // 15:40 of video, 60s shorts → ceil(940/60) = 16, clamped to 10 → band [9, 10]
    expect(computeSmartCountSuggestion(940_000, 60)).toEqual({
      rangeLabel: "00:15:40",
      lo: 9,
      hi: 10,
    });
    // 3 minutes / 60s shorts → ceil(180/60) = 3 → band [2, 4]
    expect(computeSmartCountSuggestion(180_000, 60)).toEqual({
      rangeLabel: "00:03:00",
      lo: 2,
      hi: 4,
    });
    // 30s / 60s shorts → ceil(0.5) = 1 → band [1, 2] (lo clamped to 1)
    expect(computeSmartCountSuggestion(30_000, 60)).toEqual({
      rangeLabel: "00:00:30",
      lo: 1,
      hi: 2,
    });
  });

  it("clamps the band to [1, 10]", () => {
    // 1hr / 15s = 240 → clamped to 10 → band [9, 10]
    const high = computeSmartCountSuggestion(3_600_000, 15);
    expect(high?.lo).toBe(9);
    expect(high?.hi).toBe(10);
  });
});

describe("InlineCountSelector", () => {
  it("renders 10 presets and the smart-count line", () => {
    render(
      <InlineCountSelector
        value={5}
        onChange={vi.fn()}
        rangeMs={300_000}
        lengthSeconds={60}
      />,
    );
    for (let n = 1; n <= 10; n++) {
      expect(
        screen.getByTestId(`inline-count-preset-${n}`),
      ).toBeInTheDocument();
    }
    const suggestion = screen.getByTestId("inline-count-suggestion");
    expect(suggestion.textContent).toContain("00:05:00 영상에서 60초 쇼츠라면");
    expect(suggestion.textContent).toContain("4~6개");
  });

  it("hides the suggestion line when rangeMs is 0", () => {
    render(
      <InlineCountSelector
        value={5}
        onChange={vi.fn()}
        rangeMs={0}
        lengthSeconds={60}
      />,
    );
    expect(
      screen.queryByTestId("inline-count-suggestion"),
    ).not.toBeInTheDocument();
  });
});

describe("InlineDistributionToggle", () => {
  it("renders both options with new labels", () => {
    render(
      <InlineDistributionToggle value="single" onChange={vi.fn()} />,
    );
    expect(screen.getByText("상품별 쇼츠")).toBeInTheDocument();
    expect(screen.getByText("통합 쇼츠")).toBeInTheDocument();
  });

  it("marks the active option", () => {
    render(<InlineDistributionToggle value="multi" onChange={vi.fn()} />);
    expect(
      screen.getByTestId("inline-distribution-multi").dataset.active,
    ).toBe("true");
    expect(
      screen.getByTestId("inline-distribution-single").dataset.active,
    ).toBe("false");
  });

  it("fires onChange with the toggled value", () => {
    const onChange = vi.fn();
    render(<InlineDistributionToggle value="single" onChange={onChange} />);
    fireEvent.click(screen.getByTestId("inline-distribution-multi"));
    expect(onChange).toHaveBeenCalledWith("multi");
  });
});
