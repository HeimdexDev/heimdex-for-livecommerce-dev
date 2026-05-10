import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { LoadingShortsSkeleton } from "../components/LoadingShortsSkeleton";

describe("LoadingShortsSkeleton", () => {
  it("renders the header with the literal count", () => {
    render(<LoadingShortsSkeleton count={3} />);
    const heading = screen.getByRole("heading", { level: 2 });
    expect(heading.textContent).toContain("생성된 쇼츠");
    expect(heading.textContent).toContain("3개");
  });

  it("renders count 9:16 placeholder cards", () => {
    render(<LoadingShortsSkeleton count={4} />);
    expect(
      screen.getAllByTestId("loading-shorts-skeleton-card"),
    ).toHaveLength(4);
  });

  it("renders only the header (no cards) when count is 0", () => {
    render(<LoadingShortsSkeleton count={0} />);
    expect(
      screen.queryAllByTestId("loading-shorts-skeleton-card"),
    ).toHaveLength(0);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toContain(
      "0개",
    );
  });

  it("clamps negative counts to 0", () => {
    render(<LoadingShortsSkeleton count={-1} />);
    expect(
      screen.queryAllByTestId("loading-shorts-skeleton-card"),
    ).toHaveLength(0);
    expect(screen.getByRole("heading", { level: 2 }).textContent).toContain(
      "0개",
    );
  });

  it("forwards className to the root element", () => {
    render(<LoadingShortsSkeleton count={1} className="custom-rail" />);
    expect(screen.getByTestId("loading-shorts-skeleton").className).toContain(
      "custom-rail",
    );
  });
});
