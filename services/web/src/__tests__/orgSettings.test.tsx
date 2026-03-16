import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { OrgSettingsProvider, useOrgSettings } from "@/lib/orgSettings";
import { getOrgSettings, updateOrgSettings } from "@/lib/api/orgSettings";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

const mockGetAccessToken = vi.fn().mockResolvedValue("test-token");

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    getAccessToken: mockGetAccessToken,
    isAuthenticated: true,
  }),
}));

vi.mock("@/lib/api/orgSettings", () => ({
  getOrgSettings: vi.fn(),
  updateOrgSettings: vi.fn(),
}));

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useOrgSettings", () => {
  beforeEach(() => {
    vi.mocked(getOrgSettings).mockReset();
    vi.mocked(updateOrgSettings).mockReset();
  });

  it("throws error when used outside provider", () => {
    // Suppress console.error for the expected error
    const consoleSpy = vi.spyOn(console, "error").mockImplementation(() => {});
    expect(() => renderHook(() => useOrgSettings())).toThrow(
      "useOrgSettings must be used within OrgSettingsProvider"
    );
    consoleSpy.mockRestore();
  });

  it("fetches settings on mount", async () => {
    vi.mocked(getOrgSettings).mockResolvedValue({ thumbnail_aspect_ratio: "9:16" });

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <OrgSettingsProvider>{children}</OrgSettingsProvider>
    );

    const { result } = renderHook(() => useOrgSettings(), { wrapper });

    // Initially loading with default settings
    expect(result.current.isLoading).toBe(true);
    expect(result.current.settings.thumbnail_aspect_ratio).toBe("16:9");

    // Wait for fetch to complete
    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    // React 18 Strict Mode calls useEffect twice, so it might be called 1 or 2 times
    expect(getOrgSettings).toHaveBeenCalled();
    expect(result.current.settings.thumbnail_aspect_ratio).toBe("9:16");
  });

  it("updates settings", async () => {
    vi.mocked(getOrgSettings).mockResolvedValue({ thumbnail_aspect_ratio: "16:9" });
    vi.mocked(updateOrgSettings).mockResolvedValue({ thumbnail_aspect_ratio: "9:16" });

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <OrgSettingsProvider>{children}</OrgSettingsProvider>
    );

    const { result } = renderHook(() => useOrgSettings(), { wrapper });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    await act(async () => {
      await result.current.updateThumbnailAspectRatio("9:16");
    });

    expect(updateOrgSettings).toHaveBeenCalledWith(
      { thumbnail_aspect_ratio: "9:16" },
      expect.any(Function)
    );
    
    expect(result.current.settings.thumbnail_aspect_ratio).toBe("9:16");
  });

  it("handles fetch error gracefully", async () => {
    const consoleSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.mocked(getOrgSettings).mockRejectedValue(new Error("Network error"));

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <OrgSettingsProvider>{children}</OrgSettingsProvider>
    );

    const { result } = renderHook(() => useOrgSettings(), { wrapper });

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    // Should keep default settings
    expect(result.current.settings.thumbnail_aspect_ratio).toBe("16:9");
    expect(consoleSpy).toHaveBeenCalledWith(
      "[Heimdex] Failed to fetch org settings:",
      expect.any(Error)
    );

    consoleSpy.mockRestore();
  });
});
