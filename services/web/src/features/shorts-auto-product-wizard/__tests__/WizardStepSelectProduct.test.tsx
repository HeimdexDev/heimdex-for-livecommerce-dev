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
  has_track_data: false,
  appearance_count: null,
  total_appearance_seconds: null,
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
      products: [],
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
      products: [SAMPLE_ENTRY],
    });

    render(<WizardStepSelectProduct videoId="gd_test" />);

    const card = await screen.findByTestId("product-card");
    expect(card).toBeInTheDocument();
    expect(card.textContent).toContain("테스트 가방");
  });

  it("submits createScanOrder with catalog_entry_ids when Next clicked", async () => {
    triggerEnumerationMock.mockResolvedValue({
      job_id: "j1",
      deduped: true,
    });
    getProductCatalogMock.mockResolvedValue({
      video_id: "gd_test",
      products: [SAMPLE_ENTRY],
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
      // PR 3: list shape replaces the legacy singular field.
      catalog_entry_ids: [SAMPLE_ENTRY.catalog_entry_id],
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

  it("trigger failure does NOT block access to cached catalog entries", async () => {
    // Codex P2 fix: a transient triggerEnumeration failure must not
    // strand the user — if a prior wizard run already populated the
    // catalog, those entries should still render. We swallow the
    // trigger error and let the poll be the source of truth.
    triggerEnumerationMock.mockRejectedValue(new Error("transient blip"));
    getProductCatalogMock.mockResolvedValue({
      video_id: "gd_test",
      products: [SAMPLE_ENTRY],
    });

    render(<WizardStepSelectProduct videoId="gd_test" />);

    const card = await screen.findByTestId("product-card");
    expect(card.textContent).toContain("테스트 가방");
    // The error UI does NOT take over.
    expect(screen.queryByTestId("poll-error")).not.toBeInTheDocument();
  });

  it("shows the error state when the catalog poll itself fails", async () => {
    // The poll endpoint failing IS a real error — no cached catalog
    // means there's nothing the user can do but retry.
    triggerEnumerationMock.mockResolvedValue({
      job_id: "j1",
      deduped: false,
    });
    getProductCatalogMock.mockRejectedValue(new Error("poll dead"));

    render(<WizardStepSelectProduct videoId="gd_test" />);

    const err = await screen.findByTestId("poll-error");
    expect(err.textContent).toContain("poll dead");
  });

  it("retry button restarts the polling effect", async () => {
    // Codex P2 fix: clicking 다시 시도 must trigger fresh API calls.
    // Pre-fix the button only reset local state — the useEffect's deps
    // didn't change, so no new triggerEnumeration / getProductCatalog
    // calls fired and the user was stuck on the loading state forever.
    triggerEnumerationMock.mockResolvedValue({
      job_id: "j1",
      deduped: false,
    });
    // First two calls (StrictMode dev double-mount) reject; subsequent
    // calls (after retry click) return entries.
    getProductCatalogMock
      .mockRejectedValueOnce(new Error("poll dead"))
      .mockRejectedValueOnce(new Error("poll dead"))
      .mockResolvedValue({ video_id: "gd_test", products: [SAMPLE_ENTRY] });

    render(<WizardStepSelectProduct videoId="gd_test" />);

    // Wait for the initial failure to surface.
    const err = await screen.findByTestId("poll-error");
    expect(err).toBeInTheDocument();
    const callsBefore = getProductCatalogMock.mock.calls.length;

    // Click retry — this must re-enter the effect and call the catalog
    // endpoint again (NOT just call router.refresh()).
    fireEvent.click(screen.getByText("다시 시도"));

    const card = await screen.findByTestId("product-card");
    expect(card).toBeInTheDocument();
    expect(getProductCatalogMock.mock.calls.length).toBeGreaterThan(
      callsBefore,
    );
  });
});
