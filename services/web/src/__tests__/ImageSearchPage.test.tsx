import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/images",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    getAccessToken: vi.fn().mockResolvedValue("token"),
    user: { name: "Test User", email: "test@test.com" },
    logout: vi.fn(),
    isAuthenticated: true,
    isLoading: false,
  }),
  AuthProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/dashboard/DashboardContent", () => {
  return {
    default: function MockDashboardContent(props: Record<string, unknown>) {
      return <div data-testid="dashboard-content" data-props={JSON.stringify(props)} />;
    },
  };
});

import ImageSearchContent from "@/components/ImageSearchContent";

describe("ImageSearchContent", () => {
  it("renders DashboardContent", () => {
    render(<ImageSearchContent />);
    expect(screen.getByTestId("dashboard-content")).toBeInTheDocument();
  });

  it('passes defaultContentType="image" to DashboardContent', () => {
    render(<ImageSearchContent />);
    const el = screen.getByTestId("dashboard-content");
    const props = JSON.parse(el.getAttribute("data-props") ?? "{}");
    expect(props.defaultContentType).toBe("image");
  });

  it("passes hideContentTypeToggle={true} to DashboardContent", () => {
    render(<ImageSearchContent />);
    const el = screen.getByTestId("dashboard-content");
    const props = JSON.parse(el.getAttribute("data-props") ?? "{}");
    expect(props.hideContentTypeToggle).toBe(true);
  });
});
