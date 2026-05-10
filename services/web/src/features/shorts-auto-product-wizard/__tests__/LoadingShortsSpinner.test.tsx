import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { LoadingShortsSpinner } from "../components/LoadingShortsSpinner";

describe("LoadingShortsSpinner", () => {
  it("renders the heading and sub-copy", () => {
    render(<LoadingShortsSpinner />);
    expect(
      screen.getByText("AI가 쇼츠를 생성하고 있어요"),
    ).toBeInTheDocument();
    expect(screen.getByText("평균 10초 정도 소요됩니다.")).toBeInTheDocument();
  });

  it("hides the cancel button when onCancel is not provided", () => {
    render(<LoadingShortsSpinner />);
    expect(
      screen.queryByTestId("loading-shorts-spinner-cancel"),
    ).not.toBeInTheDocument();
  });

  it("renders the cancel button when onCancel is provided", () => {
    const onCancel = vi.fn();
    render(<LoadingShortsSpinner onCancel={onCancel} />);
    expect(
      screen.getByTestId("loading-shorts-spinner-cancel"),
    ).toBeInTheDocument();
  });

  it("invokes onCancel when the cancel button is clicked", () => {
    const onCancel = vi.fn();
    render(<LoadingShortsSpinner onCancel={onCancel} />);
    fireEvent.click(screen.getByTestId("loading-shorts-spinner-cancel"));
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("forwards className to the root element", () => {
    render(<LoadingShortsSpinner className="custom-panel" />);
    expect(screen.getByTestId("loading-shorts-spinner").className).toContain(
      "custom-panel",
    );
  });
});
