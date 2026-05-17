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

const mockGetDevices = vi.fn();
const mockCreatePairingCode = vi.fn();

vi.mock("@/lib/api/devices", () => ({
  getDevices: (...args: unknown[]) => mockGetDevices(...args),
  createPairingCode: (...args: unknown[]) => mockCreatePairingCode(...args),
}));

// Must import AFTER mocks
import { DevicesSettings } from "@/features/devices";
import { PairingCodeModal } from "@/features/devices";

beforeEach(() => {
  vi.restoreAllMocks();
  mockGetDevices.mockResolvedValue({ devices: [], is_admin: true });
  mockCreatePairingCode.mockResolvedValue({
    code: "482917",
    expires_at: new Date(Date.now() + 600_000).toISOString(),
  });
});

describe("DevicesSettings", () => {
  it("renders heading and generate button", async () => {
    render(<DevicesSettings />);
    await waitFor(() => {
      expect(screen.getByText("Devices")).toBeInTheDocument();
    });
    expect(screen.getByText("Generate Pairing Code")).toBeInTheDocument();
  });

  it("shows empty state when no devices", async () => {
    render(<DevicesSettings />);
    await waitFor(() => {
      expect(screen.getByText("No devices registered yet.")).toBeInTheDocument();
    });
  });

  it("renders device list", async () => {
    mockGetDevices.mockResolvedValue({
      devices: [
        {
          device_id: "uuid-1",
          device_public_id: "cam-001",
          device_name: "Studio Camera",
          is_revoked: false,
          last_seen_at: null,
          created_at: "2026-02-15T00:00:00Z",
        },
      ],
      is_admin: true,
    });

    render(<DevicesSettings />);
    await waitFor(() => {
      expect(screen.getByText("Studio Camera")).toBeInTheDocument();
    });
    expect(screen.getByText("cam-001")).toBeInTheDocument();
    expect(screen.getByText("Active")).toBeInTheDocument();
  });

  it("shows revoked status", async () => {
    mockGetDevices.mockResolvedValue({
      devices: [
        {
          device_id: "uuid-2",
          device_public_id: "cam-old",
          device_name: "Old Camera",
          is_revoked: true,
          last_seen_at: null,
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
      is_admin: true,
    });

    render(<DevicesSettings />);
    await waitFor(() => {
      expect(screen.getByText("Revoked")).toBeInTheDocument();
    });
  });

  it("opens pairing code modal on button click", async () => {
    const user = userEvent.setup();
    render(<DevicesSettings />);

    await waitFor(() => {
      expect(screen.getByText("Generate Pairing Code")).toBeInTheDocument();
    });

    await user.click(screen.getByText("Generate Pairing Code"));

    await waitFor(() => {
      expect(screen.getByText("Device Pairing Code")).toBeInTheDocument();
    });
    expect(screen.getByText("482917")).toBeInTheDocument();
  });

  it("hides admin buttons for non-admin users but shows device list", async () => {
    mockGetDevices.mockResolvedValue({
      devices: [
        {
          device_id: "uuid-1",
          device_public_id: "cam-001",
          device_name: "Studio Camera",
          is_revoked: false,
          last_seen_at: null,
          created_at: "2026-02-15T00:00:00Z",
        },
      ],
      is_admin: false,
    });

    render(<DevicesSettings />);

    await waitFor(() => {
      expect(screen.getByText("Studio Camera")).toBeInTheDocument();
    });
    expect(screen.getByText("cam-001")).toBeInTheDocument();
    expect(screen.queryByText("Generate Pairing Code")).not.toBeInTheDocument();
  });
});

describe("PairingCodeModal", () => {
  it("displays code when open", () => {
    render(
      <PairingCodeModal
        isOpen={true}
        onClose={vi.fn()}
        code="123456"
        expiresAt={new Date(Date.now() + 300_000).toISOString()}
      />,
    );
    expect(screen.getByText("123456")).toBeInTheDocument();
    expect(screen.getByText("Copy Code")).toBeInTheDocument();
  });

  it("returns null when not open", () => {
    const { container } = render(
      <PairingCodeModal
        isOpen={false}
        onClose={vi.fn()}
        code="123456"
        expiresAt={new Date(Date.now() + 300_000).toISOString()}
      />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("shows expired state", () => {
    render(
      <PairingCodeModal
        isOpen={true}
        onClose={vi.fn()}
        code="999999"
        expiresAt={new Date(Date.now() - 60_000).toISOString()}
      />,
    );
    expect(screen.getByText("Code expired")).toBeInTheDocument();
  });

  it("calls onClose when close button clicked", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();

    render(
      <PairingCodeModal
        isOpen={true}
        onClose={onClose}
        code="123456"
        expiresAt={new Date(Date.now() + 300_000).toISOString()}
      />,
    );

    await user.click(screen.getByText("Close"));
    expect(onClose).toHaveBeenCalledOnce();
  });
});
