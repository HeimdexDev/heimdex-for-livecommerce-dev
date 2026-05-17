import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import "@testing-library/jest-dom";
import { Sidebar } from "@/components/layout/Sidebar";

let mockPathname = "/";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn(), replace: vi.fn() }),
  usePathname: () => mockPathname,
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

vi.mock("@/lib/api/devices", () => ({
  getDevices: vi.fn().mockResolvedValue({ devices: [] }),
}));

describe("Sidebar - 이미지 검색 nav item", () => {
  it('renders "이미지 검색" nav item with href="/images"', () => {
    mockPathname = "/";
    render(<Sidebar collapsed={false} onToggle={vi.fn()} />);

    const link = screen.getByRole("link", { name: /이미지 검색/ });
    expect(link).toBeInTheDocument();
    expect(link).toHaveAttribute("href", "/images");
  });

  it('appears between "동영상 검색" and "파일 동기화" in DOM order', () => {
    mockPathname = "/";
    const { container } = render(<Sidebar collapsed={false} onToggle={vi.fn()} />);

    const links = container.querySelectorAll("nav a");
    const labels = Array.from(links).map((el) => el.textContent?.trim());

    const archiveIdx = labels.findIndex((t) => t?.includes("동영상 검색"));
    const imageIdx = labels.findIndex((t) => t?.includes("이미지 검색"));
    const syncIdx = labels.findIndex((t) => t?.includes("파일 동기화"));

    expect(archiveIdx).toBeGreaterThanOrEqual(0);
    expect(imageIdx).toBeGreaterThanOrEqual(0);
    expect(syncIdx).toBeGreaterThanOrEqual(0);
    expect(archiveIdx).toBeLessThan(imageIdx);
    expect(imageIdx).toBeLessThan(syncIdx);
  });

  it('is active when pathname is "/images"', () => {
    mockPathname = "/images";
    render(<Sidebar collapsed={false} onToggle={vi.fn()} />);

    const link = screen.getByRole("link", { name: /이미지 검색/ });
    expect(link).toHaveClass("border-indigo-500");
  });

  it('"동영상 검색" is NOT active when pathname is "/images"', () => {
    mockPathname = "/images";
    render(<Sidebar collapsed={false} onToggle={vi.fn()} />);

    const archiveLink = screen.getByRole("link", { name: /동영상 검색/ });
    expect(archiveLink).not.toHaveClass("border-indigo-500");
  });
});
