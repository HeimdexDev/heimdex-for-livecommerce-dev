import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { InlineWizardContainer } from "../components/InlineWizardContainer";

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock, replace: vi.fn(), refresh: vi.fn() }),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ getAccessToken: vi.fn(async () => "test-token") }),
}));

const triggerEnumerationMock = vi.fn();
const getProductCatalogMock = vi.fn();
const createScanOrderMock = vi.fn();

vi.mock("@/lib/api/shorts-auto-product-wizard", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/api/shorts-auto-product-wizard")
  >("@/lib/api/shorts-auto-product-wizard");
  return {
    ...actual,
    triggerEnumeration: (...args: unknown[]) =>
      triggerEnumerationMock(...args),
    getProductCatalog: (...args: unknown[]) => getProductCatalogMock(...args),
    createScanOrder: (...args: unknown[]) => createScanOrderMock(...args),
  };
});

const FIVE_MIN_MS = 300_000;

describe("InlineWizardContainer", () => {
  beforeEach(() => {
    pushMock.mockReset();
    triggerEnumerationMock.mockReset();
    getProductCatalogMock.mockReset();
    createScanOrderMock.mockReset();
    triggerEnumerationMock.mockResolvedValue({ job_id: "j1", deduped: false });
    getProductCatalogMock.mockResolvedValue({
      video_id: "gd_test",
      products: [],
      scan_status: "in_progress",
    });
  });

  it("starts on the criteria step", () => {
    render(
      <InlineWizardContainer videoId="gd_test" videoDurationMs={FIVE_MIN_MS} />,
    );
    expect(
      screen.getByTestId("inline-wizard-breadcrumb-step-1-circle").dataset
        .active,
    ).toBe("true");
  });

  it("advances to product step on Next", async () => {
    const onStepChange = vi.fn();
    render(
      <InlineWizardContainer
        videoId="gd_test"
        videoDurationMs={FIVE_MIN_MS}
        onStepChange={onStepChange}
      />,
    );
    fireEvent.click(screen.getByTestId("inline-criteria-next"));
    await waitFor(() => {
      expect(
        screen.getByTestId("inline-wizard-breadcrumb-step-2-circle").dataset
          .active,
      ).toBe("true");
    });
    expect(onStepChange).toHaveBeenCalledWith("select-product");
  });

  it("preserves criteria when going back and forward", async () => {
    render(
      <InlineWizardContainer videoId="gd_test" videoDurationMs={FIVE_MIN_MS} />,
    );
    // Change length to 90 + count to 7 on the criteria step
    fireEvent.click(screen.getByTestId("inline-length-preset-90"));
    fireEvent.click(screen.getByTestId("inline-count-preset-7"));
    // Active markers should reflect the new values
    expect(
      screen.getByTestId("inline-length-preset-90").dataset.active,
    ).toBe("true");
    expect(
      screen.getByTestId("inline-count-preset-7").dataset.active,
    ).toBe("true");
    // Advance, then go back
    fireEvent.click(screen.getByTestId("inline-criteria-next"));
    await waitFor(() =>
      expect(screen.getByTestId("inline-product-back")).toBeInTheDocument(),
    );
    fireEvent.click(screen.getByTestId("inline-product-back"));
    await waitFor(() =>
      expect(screen.getByTestId("inline-criteria-next")).toBeInTheDocument(),
    );
    // Length 90 + count 7 should still be active
    expect(
      screen.getByTestId("inline-length-preset-90").dataset.active,
    ).toBe("true");
    expect(
      screen.getByTestId("inline-count-preset-7").dataset.active,
    ).toBe("true");
  });

  it("on submitOrder pushes to the legacy result route", async () => {
    getProductCatalogMock.mockResolvedValue({
      video_id: "gd_test",
      products: [
        {
          catalog_entry_id: "00000000-0000-0000-0000-000000000aaa",
          label: "테스트",
          canonical_crop_url: "https://example/c.jpg",
          enumeration_confidence: 0.9,
          prominence_score: 0.8,
          has_track_data: false,
          appearance_count: null,
          total_appearance_seconds: null,
        },
      ],
      scan_status: "complete",
    });
    createScanOrderMock.mockResolvedValue({
      parent_job_id: "00000000-0000-0000-0000-000000000999",
      run_id: "run-1",
    });
    render(
      <InlineWizardContainer videoId="gd_test" videoDurationMs={FIVE_MIN_MS} />,
    );
    fireEvent.click(screen.getByTestId("inline-criteria-next"));
    await waitFor(() => screen.getByTestId("inline-product-grid"));
    fireEvent.click(screen.getAllByTestId("inline-product-card")[0]!);
    fireEvent.click(screen.getByTestId("inline-product-next"));
    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith(
        "/export/shorts/auto/wizard/gd_test/result/00000000-0000-0000-0000-000000000999",
      );
    });
  });
});
