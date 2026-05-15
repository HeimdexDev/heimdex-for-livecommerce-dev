import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { Pagination, buildPageList } from "../Pagination";

describe("buildPageList", () => {
  it("returns all pages when total ≤ window", () => {
    expect(buildPageList(1, 5, 7)).toEqual([1, 2, 3, 4, 5]);
    expect(buildPageList(3, 7, 7)).toEqual([1, 2, 3, 4, 5, 6, 7]);
  });

  it("inserts ellipsis on the right when current is near the start", () => {
    // window=7 → 7 numbered pages total (1 first + 5 interior + 1 last).
    // current=1, total=12 → 1 2 3 4 5 6 … 12 (no left ellipsis)
    expect(buildPageList(1, 12, 7)).toEqual([1, 2, 3, 4, 5, 6, "…", 12]);
  });

  it("inserts ellipsis on the left when current is near the end", () => {
    expect(buildPageList(12, 12, 7)).toEqual([1, "…", 7, 8, 9, 10, 11, 12]);
  });

  it("inserts ellipsis on both sides when current is in the middle", () => {
    // window=7, total=20, current=10 → 1 … 8 9 10 11 12 … 20
    const list = buildPageList(10, 20, 7);
    expect(list[0]).toBe(1);
    expect(list[1]).toBe("…");
    expect(list[list.length - 1]).toBe(20);
    expect(list[list.length - 2]).toBe("…");
    // middle includes 10
    expect(list).toContain(10);
  });

  it("last page always visible even at huge totals", () => {
    expect(buildPageList(1, 100, 7).at(-1)).toBe(100);
    expect(buildPageList(50, 100, 7).at(-1)).toBe(100);
  });

  it("first page always visible", () => {
    expect(buildPageList(50, 100, 7)[0]).toBe(1);
    expect(buildPageList(100, 100, 7)[0]).toBe(1);
  });
});

describe("Pagination component", () => {
  it("returns null when only one page", () => {
    const { container } = render(
      <Pagination currentPage={1} totalPages={1} onPageChange={() => {}} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("renders with aria-label for the nav element", () => {
    render(
      <Pagination currentPage={1} totalPages={5} onPageChange={() => {}} />,
    );
    expect(screen.getByRole("navigation", { name: "페이지" })).toBeInTheDocument();
  });

  it("sets aria-current='page' on the active page", () => {
    render(
      <Pagination currentPage={3} totalPages={5} onPageChange={() => {}} />,
    );
    const active = screen.getByRole("button", { name: "3 페이지" });
    expect(active).toHaveAttribute("aria-current", "page");
    const other = screen.getByRole("button", { name: "2 페이지" });
    expect(other).not.toHaveAttribute("aria-current");
  });

  it("disables prev/first on page 1", () => {
    render(
      <Pagination currentPage={1} totalPages={5} onPageChange={() => {}} />,
    );
    expect(screen.getByRole("button", { name: "첫 페이지" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "이전 페이지" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "다음 페이지" })).not.toBeDisabled();
  });

  it("disables next/last on the last page", () => {
    render(
      <Pagination currentPage={5} totalPages={5} onPageChange={() => {}} />,
    );
    expect(screen.getByRole("button", { name: "다음 페이지" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "마지막 페이지" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "이전 페이지" })).not.toBeDisabled();
  });

  it("fires onPageChange with the clicked number", () => {
    const onPageChange = vi.fn();
    render(
      <Pagination currentPage={1} totalPages={5} onPageChange={onPageChange} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "3 페이지" }));
    expect(onPageChange).toHaveBeenCalledWith(3);
  });

  it("prev/next emit current±1; first/last emit 1/total", () => {
    const onPageChange = vi.fn();
    render(
      <Pagination currentPage={3} totalPages={7} onPageChange={onPageChange} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "이전 페이지" }));
    expect(onPageChange).toHaveBeenLastCalledWith(2);
    fireEvent.click(screen.getByRole("button", { name: "다음 페이지" }));
    expect(onPageChange).toHaveBeenLastCalledWith(4);
    fireEvent.click(screen.getByRole("button", { name: "첫 페이지" }));
    expect(onPageChange).toHaveBeenLastCalledWith(1);
    fireEvent.click(screen.getByRole("button", { name: "마지막 페이지" }));
    expect(onPageChange).toHaveBeenLastCalledWith(7);
  });

  it("clamps out-of-range currentPage defensively", () => {
    // currentPage=99 with totalPages=5 → safePage should be 5, last button
    // disabled.
    render(
      <Pagination currentPage={99} totalPages={5} onPageChange={() => {}} />,
    );
    expect(screen.getByRole("button", { name: "마지막 페이지" })).toBeDisabled();
  });

  it("renders ellipsis as visible text when windowed", () => {
    render(
      <Pagination currentPage={10} totalPages={20} onPageChange={() => {}} />,
    );
    // At least one "…" must render in the DOM
    const matches = screen.getAllByText("…");
    expect(matches.length).toBeGreaterThanOrEqual(1);
  });
});
