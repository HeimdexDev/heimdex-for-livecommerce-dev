import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { SubtitleSearchInput } from "../components/SubtitleSearchInput";

describe("SubtitleSearchInput", () => {
  it("renders the placeholder", () => {
    render(<SubtitleSearchInput query="" onQueryChange={vi.fn()} />);
    expect(
      screen.getByPlaceholderText("찾고 싶은 자막을 검색하세요."),
    ).toBeInTheDocument();
  });

  it("typing commits onQueryChange when not composing", () => {
    const onQueryChange = vi.fn();
    render(<SubtitleSearchInput query="" onQueryChange={onQueryChange} />);
    fireEvent.change(screen.getByTestId("subtitle-search-input"), {
      target: { value: "search" },
    });
    expect(onQueryChange).toHaveBeenCalledWith("search");
  });

  it("does NOT commit while IME composition is in progress", () => {
    const onQueryChange = vi.fn();
    render(<SubtitleSearchInput query="" onQueryChange={onQueryChange} />);
    const input = screen.getByTestId("subtitle-search-input");
    fireEvent.compositionStart(input);
    fireEvent.change(input, { target: { value: "한" } });
    expect(onQueryChange).not.toHaveBeenCalled();
    // Composition end commits with the final value.
    fireEvent.compositionEnd(input, { currentTarget: input });
    expect(onQueryChange).toHaveBeenCalledWith("한");
  });

  it("clear button appears only when there is a value", () => {
    const { rerender } = render(
      <SubtitleSearchInput query="" onQueryChange={vi.fn()} />,
    );
    expect(
      screen.queryByTestId("subtitle-search-input-clear"),
    ).not.toBeInTheDocument();
    rerender(<SubtitleSearchInput query="x" onQueryChange={vi.fn()} />);
    expect(
      screen.getByTestId("subtitle-search-input-clear"),
    ).toBeInTheDocument();
  });

  it("clear button resets the query", () => {
    const onQueryChange = vi.fn();
    render(<SubtitleSearchInput query="x" onQueryChange={onQueryChange} />);
    fireEvent.click(screen.getByTestId("subtitle-search-input-clear"));
    expect(onQueryChange).toHaveBeenCalledWith("");
  });
});
