import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { StyleTab } from "../components/StyleTab";
import {
  makeDefaultStyle,
  type SubtitleStyleDraft,
} from "../lib/global-style";

const DEFAULT: SubtitleStyleDraft = makeDefaultStyle();

describe("StyleTab — non-mixed state", () => {
  it("renders all the top-row controls", () => {
    render(
      <StyleTab currentStyle={DEFAULT} onStyleChange={vi.fn()} />,
    );
    expect(screen.getByTestId("style-tab-font-family")).toBeInTheDocument();
    expect(screen.getByTestId("style-tab-font-size")).toBeInTheDocument();
    expect(screen.getByTestId("style-tab-font-bold")).toBeInTheDocument();
    expect(screen.getByTestId("style-tab-text-align")).toBeInTheDocument();
    expect(screen.getByTestId("style-tab-font-color")).toBeInTheDocument();
  });

  it("does NOT show the mixed banner when style is uniform", () => {
    render(
      <StyleTab currentStyle={DEFAULT} onStyleChange={vi.fn()} />,
    );
    expect(
      screen.queryByTestId("style-tab-mixed-banner"),
    ).not.toBeInTheDocument();
  });

  it("font-family change fires onStyleChange with the new family", () => {
    const onStyleChange = vi.fn();
    render(
      <StyleTab currentStyle={DEFAULT} onStyleChange={onStyleChange} />,
    );
    fireEvent.change(screen.getByTestId("style-tab-font-family"), {
      target: { value: "Noto Sans KR" },
    });
    expect(onStyleChange).toHaveBeenCalledWith(
      expect.objectContaining({ font_family: "Noto Sans KR" }),
    );
  });

  it("font-bold toggle flips weight between 700 and 400", () => {
    const onStyleChange = vi.fn();
    const lightStyle = { ...DEFAULT, font_weight: 400 };
    render(
      <StyleTab currentStyle={lightStyle} onStyleChange={onStyleChange} />,
    );
    fireEvent.click(screen.getByTestId("style-tab-font-bold"));
    expect(onStyleChange).toHaveBeenCalledWith(
      expect.objectContaining({ font_weight: 700 }),
    );
  });

  it("font-size increment / decrement clamp at the bounds", () => {
    const onStyleChange = vi.fn();
    render(
      <StyleTab currentStyle={DEFAULT} onStyleChange={onStyleChange} />,
    );
    fireEvent.click(screen.getByTestId("style-tab-font-size-inc"));
    expect(onStyleChange).toHaveBeenCalledWith(
      expect.objectContaining({ font_size_px: DEFAULT.font_size_px + 1 }),
    );
  });

  it("opacity slider commits the new percentage", () => {
    const onStyleChange = vi.fn();
    render(
      <StyleTab currentStyle={DEFAULT} onStyleChange={onStyleChange} />,
    );
    fireEvent.change(screen.getByTestId("style-tab-opacity-slider"), {
      target: { value: "42" },
    });
    expect(onStyleChange).toHaveBeenCalledWith(
      expect.objectContaining({ background_opacity: 0.42 }),
    );
  });

  it("shadow controls hide when shadow_enabled is false", () => {
    const noShadow = { ...DEFAULT, shadow_enabled: false };
    render(<StyleTab currentStyle={noShadow} onStyleChange={vi.fn()} />);
    expect(
      screen.queryByTestId("style-tab-shadow-offset-x"),
    ).not.toBeInTheDocument();
  });

  it("toggling shadow on reveals its sub-controls", () => {
    const onStyleChange = vi.fn();
    const noShadow = { ...DEFAULT, shadow_enabled: false };
    render(<StyleTab currentStyle={noShadow} onStyleChange={onStyleChange} />);
    fireEvent.click(screen.getByTestId("style-tab-shadow-toggle"));
    expect(onStyleChange).toHaveBeenCalledWith(
      expect.objectContaining({ shadow_enabled: true }),
    );
  });

  it("position-x percentage maps to fractional position", () => {
    const onStyleChange = vi.fn();
    render(<StyleTab currentStyle={DEFAULT} onStyleChange={onStyleChange} />);
    fireEvent.click(screen.getByTestId("style-tab-position-x-inc"));
    const lastCall = onStyleChange.mock.calls.at(-1)?.[0] as SubtitleStyleDraft;
    expect(lastCall.position_x).toBeCloseTo(
      Math.min(1, DEFAULT.position_x + 0.01),
    );
  });
});

describe("StyleTab — mixed state", () => {
  it("shows the mixed banner when currentStyle is null", () => {
    render(<StyleTab currentStyle={null} onStyleChange={vi.fn()} />);
    expect(screen.getByTestId("style-tab-mixed-banner")).toBeInTheDocument();
  });

  it("'글로벌로 적용' fires onApplyToAll", () => {
    const onApplyToAll = vi.fn();
    render(
      <StyleTab
        currentStyle={null}
        onStyleChange={vi.fn()}
        onApplyToAll={onApplyToAll}
      />,
    );
    fireEvent.click(screen.getByTestId("style-tab-apply-all"));
    expect(onApplyToAll).toHaveBeenCalledTimes(1);
  });

  it("falls back to default style for the controls when mixed", () => {
    render(<StyleTab currentStyle={null} onStyleChange={vi.fn()} />);
    // Font family should reflect the default
    const select = screen.getByTestId(
      "style-tab-font-family",
    ) as HTMLSelectElement;
    expect(select.value).toBe(DEFAULT.font_family);
  });
});

describe("StyleTab — disabled", () => {
  it("disables every control when disabled prop is true", () => {
    render(
      <StyleTab
        currentStyle={DEFAULT}
        onStyleChange={vi.fn()}
        disabled
      />,
    );
    expect(screen.getByTestId("style-tab-font-family")).toBeDisabled();
    expect(screen.getByTestId("style-tab-font-bold")).toBeDisabled();
    expect(screen.getByTestId("style-tab-opacity-slider")).toBeDisabled();
    expect(screen.getByTestId("style-tab-shadow-toggle")).toBeDisabled();
  });
});
