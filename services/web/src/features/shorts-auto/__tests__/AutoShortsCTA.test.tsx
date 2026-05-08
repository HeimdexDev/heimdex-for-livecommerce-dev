import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { AutoShortsCTA } from "../components/AutoShortsCTA";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ getAccessToken: vi.fn(async () => "test-token") }),
}));

const fetchMock = vi.fn();

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  // Availability probe → "enabled" (the only state in which CTA renders).
  fetchMock.mockResolvedValue({
    ok: true,
    status: 200,
    json: async () => ({ availability: "enabled" }),
  });
});

afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

describe("AutoShortsCTA", () => {
  it("renders a button (not a link) when onClick is supplied", async () => {
    const onClick = vi.fn();
    render(<AutoShortsCTA videoId="gd_test" onClick={onClick} />);
    const btn = await waitFor(() => screen.getByRole("button"));
    expect(btn.tagName).toBe("BUTTON");
    expect(btn.textContent).toContain("AI 쇼츠 생성");
  });

  it("fires the onClick callback (does NOT navigate) when clicked", async () => {
    const onClick = vi.fn();
    render(<AutoShortsCTA videoId="gd_test" onClick={onClick} />);
    const btn = await waitFor(() => screen.getByRole("button"));
    fireEvent.click(btn);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it("falls back to a deep link when onClick is omitted", async () => {
    render(<AutoShortsCTA videoId="gd_test" />);
    const link = await waitFor(() => screen.getByRole("link"));
    expect(link.tagName).toBe("A");
    expect(link.getAttribute("href")).toBe(
      "/export/shorts/auto/wizard/gd_test/criteria",
    );
  });
});
