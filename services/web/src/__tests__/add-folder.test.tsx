import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    getAccessToken: vi.fn().mockResolvedValue("test-token"),
    isAuthenticated: true,
    isLoading: false,
    user: { email: "admin@test.com", name: "Admin" },
    error: null,
    login: vi.fn(),
    loginWithCredentials: vi.fn(),
    logout: vi.fn(),
    isAuth0Enabled: false,
  }),
  getOrgSlug: () => "test-org",
  isAuth0Enabled: false,
}));

const mockCreateFolderIntent = vi.fn();

vi.mock("@/lib/api/agent-intents", () => ({
  createFolderIntent: (...args: unknown[]) => mockCreateFolderIntent(...args),
}));

import { AddFolderButton, AddFolderModal } from "@/features/folders";

const mockDevices = [
  {
    device_id: "uuid-1",
    device_public_id: "dev-001",
    device_name: "Studio Mac",
    is_revoked: false,
    last_seen_at: null,
    created_at: "2026-02-15T00:00:00Z",
  },
];

beforeEach(() => {
  vi.restoreAllMocks();
  mockCreateFolderIntent.mockResolvedValue({
    intent_code: "test-intent-code-abcdef12",
    type: "folder_add",
    expires_at: new Date(Date.now() + 600_000).toISOString(),
    deep_link_url: "heimdex://add-folder?code=test-intent-code-abcdef12",
  });
});

describe("AddFolderButton", () => {
  it("renders Add Folder button when devices exist", () => {
    render(<AddFolderButton devices={mockDevices} />);
    expect(screen.getByText("Add Folder")).toBeInTheDocument();
  });

  it("does not render when no active devices", () => {
    const { container } = render(<AddFolderButton devices={[]} />);
    expect(container.innerHTML).toBe("");
  });

  it("does not render when all devices are revoked", () => {
    const revoked = [{ ...mockDevices[0], is_revoked: true }];
    const { container } = render(<AddFolderButton devices={revoked} />);
    expect(container.innerHTML).toBe("");
  });

  it("creates intent and shows modal on click", async () => {
    const user = userEvent.setup();
    render(<AddFolderButton devices={mockDevices} />);

    await user.click(screen.getByText("Add Folder"));

    await waitFor(() => {
      expect(
        screen.getByText("Add Folder", { selector: "h3" }),
      ).toBeInTheDocument();
    });
    expect(mockCreateFolderIntent).toHaveBeenCalledWith(
      expect.any(Function),
      "uuid-1",
    );
  });

  it("shows device selector when multiple active devices", () => {
    const multiDevices = [
      ...mockDevices,
      {
        device_id: "uuid-2",
        device_public_id: "dev-002",
        device_name: "Editing PC",
        is_revoked: false,
        last_seen_at: null,
        created_at: "2026-02-15T00:00:00Z",
      },
    ];
    render(<AddFolderButton devices={multiDevices} />);
    expect(screen.getByText("Select device...")).toBeInTheDocument();
  });

  it("handles API error gracefully", async () => {
    const { ApiError } = await import("@/lib/types");
    mockCreateFolderIntent.mockRejectedValue(
      new ApiError("forbidden", 403, "Not admin"),
    );

    const user = userEvent.setup();
    render(<AddFolderButton devices={mockDevices} />);
    await user.click(screen.getByText("Add Folder"));

    await waitFor(() => {
      expect(
        screen.getByText("You need admin access to add folders."),
      ).toBeInTheDocument();
    });
  });
});

describe("AddFolderModal", () => {
  it("displays deep link when open", () => {
    render(
      <AddFolderModal
        isOpen={true}
        onClose={vi.fn()}
        deepLinkUrl="heimdex://add-folder?code=abc123"
        expiresAt={new Date(Date.now() + 300_000).toISOString()}
      />,
    );
    expect(
      screen.getByText("Add Folder", { selector: "h3" }),
    ).toBeInTheDocument();
    expect(screen.getByText("Open Heimdex Agent")).toBeInTheDocument();
  });

  it("returns null when not open", () => {
    const { container } = render(
      <AddFolderModal
        isOpen={false}
        onClose={vi.fn()}
        deepLinkUrl="heimdex://add-folder?code=abc123"
        expiresAt={new Date(Date.now() + 300_000).toISOString()}
      />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("shows expired state", () => {
    render(
      <AddFolderModal
        isOpen={true}
        onClose={vi.fn()}
        deepLinkUrl="heimdex://add-folder?code=abc123"
        expiresAt={new Date(Date.now() - 60_000).toISOString()}
      />,
    );
    expect(screen.getByText("Link expired")).toBeInTheDocument();
  });

  it("calls onClose when close button clicked", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(
      <AddFolderModal
        isOpen={true}
        onClose={onClose}
        deepLinkUrl="heimdex://add-folder?code=abc123"
        expiresAt={new Date(Date.now() + 300_000).toISOString()}
      />,
    );
    await user.click(screen.getByText("Close"));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
