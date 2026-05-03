import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { WizardStepSelectProduct } from "../pages/WizardStepSelectProduct";

const pushMock = vi.fn();
const replaceMock = vi.fn();
const refreshMock = vi.fn();

let mockSearchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: pushMock,
    replace: replaceMock,
    refresh: refreshMock,
  }),
  useSearchParams: () => mockSearchParams,
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

const VALID_CRITERIA_PARAMS = new URLSearchParams({
  length: "60",
  count: "5",
  distribution: "single",
  language: "ko",
  intent: "commit",
});

const SAMPLE_ENTRY = {
  catalog_entry_id: "00000000-0000-0000-0000-000000000aaa",
  label: "테스트 가방",
  canonical_crop_url: "https://example/crop.jpg",
  enumeration_confidence: 0.9,
  prominence_score: 0.8,
  appearance_count: null,
};

describe("WizardStepSelectProduct", () => {
  beforeEach(() => {
    pushMock.mockReset();
    replaceMock.mockReset();
    refreshMock.mockReset();
    triggerEnumerationMock.mockReset();
    getProductCatalogMock.mockReset();
    createScanOrderMock.mockReset();
    mockSearchParams = VALID_CRITERIA_PARAMS;
  });

  it("kicks off enumeration on mount and renders the loading state", async () => {
    triggerEnumerationMock.mockResolvedValue({
      job_id: "j1",
      deduped: false,
    });
    // Empty first poll → still loading.
    getProductCatalogMock.mockResolvedValue({
      video_id: "gd_test",
      entries: [],
    });

    render(<WizardStepSelectProduct videoId="gd_test" />);

    expect(screen.getByTestId("enumeration-loading")).toBeInTheDocument();
    await waitFor(() =>
      expect(triggerEnumerationMock).toHaveBeenCalledTimes(1),
    );
    expect(triggerEnumerationMock.mock.calls[0][0]).toBe("gd_test");
    expect(triggerEnumerationMock.mock.calls[0][1]).toEqual({
      duration_preset_sec: 60,
    });
  });

  it("renders the product grid when polling returns entries", async () => {
    triggerEnumerationMock.mockResolvedValue({
      job_id: "j1",
      deduped: true,
    });
    getProductCatalogMock.mockResolvedValue({
      video_id: "gd_test",
      entries: [SAMPLE_ENTRY],
    });

    render(<WizardStepSelectProduct videoId="gd_test" />);

    const card = await screen.findByTestId("product-card");
    expect(card).toBeInTheDocument();
    expect(card.textContent).toContain("테스트 가방");
  });

  it("submits createScanOrder with catalog_entry_id when Next clicked", async () => {
    triggerEnumerationMock.mockResolvedValue({
      job_id: "j1",
      deduped: true,
    });
    getProductCatalogMock.mockResolvedValue({
      video_id: "gd_test",
      entries: [SAMPLE_ENTRY],
    });
    createScanOrderMock.mockResolvedValue({
      parent_job_id: "00000000-0000-0000-0000-000000000123",
      deduped: false,
    });

    render(<WizardStepSelectProduct videoId="gd_test" />);

    const card = await screen.findByTestId("product-card");
    // Next is disabled until a card is selected.
    const nextBefore = screen.getByTestId(
      "wizard-next",
    ) as HTMLButtonElement;
    expect(nextBefore.disabled).toBe(true);

    fireEvent.click(card);
    const nextAfter = screen.getByTestId(
      "wizard-next",
    ) as HTMLButtonElement;
    expect(nextAfter.disabled).toBe(false);

    fireEvent.click(nextAfter);

    await waitFor(() => expect(createScanOrderMock).toHaveBeenCalledTimes(1));
    expect(createScanOrderMock.mock.calls[0][0]).toBe("gd_test");
    expect(createScanOrderMock.mock.calls[0][1]).toMatchObject({
      length_seconds: 60,
      requested_count: 5,
      product_distribution: "single",
      language: "ko",
      intent: "commit",
      catalog_entry_id: SAMPLE_ENTRY.catalog_entry_id,
    });
    await waitFor(() =>
      expect(pushMock).toHaveBeenCalledWith(
        "/export/shorts/auto/wizard/gd_test/result/00000000-0000-0000-0000-000000000123",
      ),
    );
  });

  it("redirects to /criteria when URL params are missing", () => {
    mockSearchParams = new URLSearchParams(); // no length / count / etc.
    render(<WizardStepSelectProduct videoId="gd_test" />);
    expect(replaceMock).toHaveBeenCalledWith(
      "/export/shorts/auto/wizard/gd_test/criteria",
    );
    // Critically: no API calls fire on the bad-params path.
    expect(triggerEnumerationMock).not.toHaveBeenCalled();
    expect(getProductCatalogMock).not.toHaveBeenCalled();
  });

  it("shows the error state when triggerEnumeration rejects", async () => {
    // Use mockRejectedValue (not …Once) because React 18+ strict-mode
    // mounts the effect twice in dev/test; both runs must reject for
    // the assertion to find the original error message.
    triggerEnumerationMock.mockRejectedValue(new Error("network down"));

    render(<WizardStepSelectProduct videoId="gd_test" />);

    const err = await screen.findByTestId("poll-error");
    expect(err.textContent).toContain("network down");
  });
});
