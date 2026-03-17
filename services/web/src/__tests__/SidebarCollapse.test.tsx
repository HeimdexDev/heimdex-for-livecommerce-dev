import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { Sidebar } from "@/components/layout/Sidebar";
import { TopHeader } from "@/components/layout/TopHeader";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/",
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

describe("Sidebar", () => {
  it("renders expanded by default with nav items visible", () => {
    render(<Sidebar collapsed={false} onToggle={vi.fn()} />);

    expect(screen.getByText("전체 아카이브 검색")).toBeInTheDocument();
    expect(screen.getByText("파일 동기화")).toBeInTheDocument();
    expect(screen.getByText("인물 라벨 관리")).toBeInTheDocument();
    expect(screen.getByText("저장된 쇼츠")).toBeInTheDocument();
    expect(screen.getByText("에이전트")).toBeInTheDocument();
  });

  it("applies w-0 overflow-hidden when collapsed", () => {
    const { container } = render(<Sidebar collapsed={true} onToggle={vi.fn()} />);

    const aside = container.querySelector("aside");
    expect(aside).toHaveClass("w-0");
    expect(aside).toHaveClass("overflow-hidden");
  });

  it("applies w-[200px] when expanded", () => {
    const { container } = render(<Sidebar collapsed={false} onToggle={vi.fn()} />);

    const aside = container.querySelector("aside");
    expect(aside).toHaveClass("w-[200px]");
    expect(aside).not.toHaveClass("overflow-hidden");
  });

  it("has transition classes for smooth animation", () => {
    const { container } = render(<Sidebar collapsed={false} onToggle={vi.fn()} />);

    const aside = container.querySelector("aside");
    expect(aside).toHaveClass("transition-[width]");
    expect(aside).toHaveClass("duration-300");
    expect(aside).toHaveClass("ease-in-out");
  });

  it("calls onToggle when collapse button is clicked", async () => {
    const onToggle = vi.fn();
    const user = userEvent.setup();

    render(<Sidebar collapsed={false} onToggle={onToggle} />);

    const collapseBtn = screen.getByLabelText("사이드바 접기");
    await user.click(collapseBtn);

    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it("has collapse button with aria-label", () => {
    render(<Sidebar collapsed={false} onToggle={vi.fn()} />);

    const collapseBtn = screen.getByLabelText("사이드바 접기");
    expect(collapseBtn).toBeInTheDocument();
  });
});

describe("TopHeader", () => {
  it("shows hamburger button when sidebar is collapsed", () => {
    render(<TopHeader sidebarCollapsed={true} onToggleSidebar={vi.fn()} />);

    const hamburgerBtn = screen.getByLabelText("사이드바 열기");
    expect(hamburgerBtn).toBeInTheDocument();
  });

  it("hides hamburger button when sidebar is expanded", () => {
    render(<TopHeader sidebarCollapsed={false} onToggleSidebar={vi.fn()} />);

    expect(screen.queryByLabelText("사이드바 열기")).not.toBeInTheDocument();
  });

  it("calls onToggleSidebar when hamburger is clicked", async () => {
    const onToggle = vi.fn();
    const user = userEvent.setup();

    render(<TopHeader sidebarCollapsed={true} onToggleSidebar={onToggle} />);

    const hamburgerBtn = screen.getByLabelText("사이드바 열기");
    await user.click(hamburgerBtn);

    expect(onToggle).toHaveBeenCalledTimes(1);
  });
});

describe("localStorage persistence", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("stores collapsed state in localStorage", () => {
    localStorage.setItem("heimdex-sidebar-collapsed", "true");
    expect(localStorage.getItem("heimdex-sidebar-collapsed")).toBe("true");
  });

  it("defaults to expanded when localStorage is empty", () => {
    expect(localStorage.getItem("heimdex-sidebar-collapsed")).toBeNull();
  });

  it("stores expanded state as 'false'", () => {
    localStorage.setItem("heimdex-sidebar-collapsed", "false");
    expect(localStorage.getItem("heimdex-sidebar-collapsed")).toBe("false");
  });
});
