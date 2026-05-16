import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { RightPanelTabs } from "../components/RightPanelTabs";

describe("RightPanelTabs", () => {
  it("renders both tabs", () => {
    render(<RightPanelTabs activeTab="subtitles" onTabChange={vi.fn()} />);
    expect(screen.getByText("자막")).toBeInTheDocument();
    expect(screen.getByText("스타일")).toBeInTheDocument();
    expect(screen.queryByText("템플릿")).not.toBeInTheDocument();
  });

  it("marks the active tab visually", () => {
    render(<RightPanelTabs activeTab="style" onTabChange={vi.fn()} />);
    const subs = screen.getByTestId("right-panel-tab-subtitles");
    const style = screen.getByTestId("right-panel-tab-style");
    expect(subs.dataset.active).toBe("false");
    expect(style.dataset.active).toBe("true");
    expect(style.className).toMatch(/border-indigo-500/);
  });

  it("fires onTabChange on click", () => {
    const onTabChange = vi.fn();
    render(<RightPanelTabs activeTab="subtitles" onTabChange={onTabChange} />);
    fireEvent.click(screen.getByTestId("right-panel-tab-style"));
    expect(onTabChange).toHaveBeenCalledWith("style");
  });

  it("ArrowRight rotates to the next tab", () => {
    const onTabChange = vi.fn();
    render(<RightPanelTabs activeTab="subtitles" onTabChange={onTabChange} />);
    fireEvent.keyDown(screen.getByTestId("right-panel-tabs"), {
      key: "ArrowRight",
    });
    expect(onTabChange).toHaveBeenCalledWith("style");
  });

  it("ArrowLeft wraps from the first to the last tab", () => {
    const onTabChange = vi.fn();
    render(<RightPanelTabs activeTab="subtitles" onTabChange={onTabChange} />);
    fireEvent.keyDown(screen.getByTestId("right-panel-tabs"), {
      key: "ArrowLeft",
    });
    expect(onTabChange).toHaveBeenCalledWith("style");
  });

  it("non-arrow keys are ignored", () => {
    const onTabChange = vi.fn();
    render(<RightPanelTabs activeTab="subtitles" onTabChange={onTabChange} />);
    fireEvent.keyDown(screen.getByTestId("right-panel-tabs"), { key: "Tab" });
    expect(onTabChange).not.toHaveBeenCalled();
  });

  it("forwards className to the root", () => {
    render(
      <RightPanelTabs
        activeTab="subtitles"
        onTabChange={vi.fn()}
        className="custom-strip"
      />,
    );
    expect(screen.getByTestId("right-panel-tabs").className).toContain(
      "custom-strip",
    );
  });
});
