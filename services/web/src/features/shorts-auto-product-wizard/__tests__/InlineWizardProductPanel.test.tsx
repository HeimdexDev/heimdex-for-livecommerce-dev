import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { InlineWizardProductPanel } from "../components/InlineWizardProductPanel";
import {
  DEFAULT_CRITERIA,
  type WizardCriteriaDraft,
} from "../components/InlineWizardCriteriaPanel";

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

const SAMPLE_ENTRIES = [
  {
    catalog_entry_id: "00000000-0000-0000-0000-000000000aaa",
    label: "테스트 가방",
    canonical_crop_url: "https://example/crop1.jpg",
    enumeration_confidence: 0.9,
    prominence_score: 0.8,
    has_track_data: false,
    appearance_count: null,
    total_appearance_seconds: null,
  },
  {
    catalog_entry_id: "00000000-0000-0000-0000-000000000bbb",
    label: "테스트 신발",
    canonical_crop_url: "https://example/crop2.jpg",
    enumeration_confidence: 0.8,
    prominence_score: 0.7,
    has_track_data: false,
    appearance_count: null,
    total_appearance_seconds: null,
  },
];

const FIVE_MIN_MS = 300_000;

function renderPanel(
  overrides: { criteria?: Partial<WizardCriteriaDraft> } = {},
) {
  const onSubmitOrder = vi.fn();
  const onBack = vi.fn();
  const utils = render(
    <InlineWizardProductPanel
      videoId="gd_test"
      videoDurationMs={FIVE_MIN_MS}
      criteria={{ ...DEFAULT_CRITERIA, ...overrides.criteria }}
      onSubmitOrder={onSubmitOrder}
      onBack={onBack}
    />,
  );
  return { ...utils, onSubmitOrder, onBack };
}

describe("InlineWizardProductPanel", () => {
  beforeEach(() => {
    triggerEnumerationMock.mockReset();
    getProductCatalogMock.mockReset();
    createScanOrderMock.mockReset();
  });

  it("shows the loading state and triggers enumeration on mount", async () => {
    triggerEnumerationMock.mockResolvedValue({ job_id: "j1", deduped: false });
    getProductCatalogMock.mockResolvedValue({
      video_id: "gd_test",
      products: [],
      scan_status: "in_progress",
    });
    renderPanel();
    expect(screen.getByTestId("inline-product-loading")).toBeInTheDocument();
    await waitFor(() => {
      expect(triggerEnumerationMock).toHaveBeenCalledWith(
        "gd_test",
        { duration_preset_sec: 60 },
        expect.any(Function),
      );
    });
  });

  it("renders the product grid when entries arrive", async () => {
    triggerEnumerationMock.mockResolvedValue({ job_id: "j1", deduped: false });
    getProductCatalogMock.mockResolvedValue({
      video_id: "gd_test",
      products: SAMPLE_ENTRIES,
      scan_status: "complete",
    });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("inline-product-grid")).toBeInTheDocument();
    });
    expect(screen.getAllByTestId("inline-product-card")).toHaveLength(2);
  });

  it("clicking cards toggles multi-select; both can be on", async () => {
    triggerEnumerationMock.mockResolvedValue({ job_id: "j1", deduped: false });
    getProductCatalogMock.mockResolvedValue({
      video_id: "gd_test",
      products: SAMPLE_ENTRIES,
      scan_status: "complete",
    });
    renderPanel({ criteria: { requested_count: 2 } });
    await waitFor(() => screen.getByTestId("inline-product-grid"));
    const cards = screen.getAllByTestId("inline-product-card");
    fireEvent.click(cards[0]!);
    expect(cards[0]!.dataset.selected).toBe("true");
    expect(cards[1]!.dataset.selected).toBe("false");
    // PR 3: clicking another card ADDS to the set (multi-select),
    // doesn't replace.
    fireEvent.click(cards[1]!);
    expect(cards[0]!.dataset.selected).toBe("true");
    expect(cards[1]!.dataset.selected).toBe("true");
  });

  it("re-clicking a selected card deselects it", async () => {
    triggerEnumerationMock.mockResolvedValue({ job_id: "j1", deduped: false });
    getProductCatalogMock.mockResolvedValue({
      video_id: "gd_test",
      products: SAMPLE_ENTRIES,
      scan_status: "complete",
    });
    renderPanel({ criteria: { requested_count: 2 } });
    await waitFor(() => screen.getByTestId("inline-product-grid"));
    const card = screen.getAllByTestId("inline-product-card")[0]!;
    fireEvent.click(card);
    expect(card.dataset.selected).toBe("true");
    fireEvent.click(card);
    expect(card.dataset.selected).toBe("false");
  });

  it("clicking a 3rd card at cap=2 is silently ignored", async () => {
    // 3 sample entries, cap=2: the third click should be ignored
    // (cap enforcement on the client side).
    const THREE_ENTRIES = [
      ...SAMPLE_ENTRIES,
      {
        catalog_entry_id: "00000000-0000-0000-0000-000000000ccc",
        label: "Three",
        canonical_crop_url: null,
        enumeration_confidence: 0.7,
        prominence_score: null,
        has_track_data: false,
        appearance_count: null,
        total_appearance_seconds: null,
        enumeration_source: "vision",
        first_mention_ms: null,
        example_quote: null,
      },
    ];
    triggerEnumerationMock.mockResolvedValue({ job_id: "j1", deduped: false });
    getProductCatalogMock.mockResolvedValue({
      video_id: "gd_test",
      products: THREE_ENTRIES,
      scan_status: "complete",
    });
    renderPanel({ criteria: { requested_count: 2 } });
    await waitFor(() => screen.getByTestId("inline-product-grid"));
    const cards = screen.getAllByTestId("inline-product-card");
    fireEvent.click(cards[0]!);
    fireEvent.click(cards[1]!);
    fireEvent.click(cards[2]!);
    expect(cards[0]!.dataset.selected).toBe("true");
    expect(cards[1]!.dataset.selected).toBe("true");
    expect(cards[2]!.dataset.selected).toBe("false");
    // The at-cap card is also disabled visually (button.disabled).
    expect((cards[2]! as HTMLButtonElement).disabled).toBe(true);
  });

  it("counter renders K/N format", async () => {
    triggerEnumerationMock.mockResolvedValue({ job_id: "j1", deduped: false });
    getProductCatalogMock.mockResolvedValue({
      video_id: "gd_test",
      products: SAMPLE_ENTRIES,
      scan_status: "complete",
    });
    renderPanel({ criteria: { requested_count: 4 } });
    await waitFor(() => screen.getByTestId("inline-product-grid"));
    expect(screen.getByText(/2개 중 0\/4개 선택/)).toBeInTheDocument();
    fireEvent.click(screen.getAllByTestId("inline-product-card")[0]!);
    expect(screen.getByText(/2개 중 1\/4개 선택/)).toBeInTheDocument();
  });

  it("submits with hardcoded language=ko + intent=commit + sorted catalog_entry_ids", async () => {
    triggerEnumerationMock.mockResolvedValue({ job_id: "j1", deduped: false });
    getProductCatalogMock.mockResolvedValue({
      video_id: "gd_test",
      products: SAMPLE_ENTRIES,
      scan_status: "complete",
    });
    createScanOrderMock.mockResolvedValue({
      parent_job_id: "00000000-0000-0000-0000-000000000999",
      run_id: "run-1",
    });
    const { onSubmitOrder } = renderPanel({
      criteria: {
        length_seconds: 90,
        requested_count: 4,
        time_range_start_ms: 60_000,
        time_range_end_ms: 240_000,
        product_distribution: "multi",
      },
    });
    await waitFor(() => screen.getByTestId("inline-product-grid"));
    // Click both cards (multi-select). Click order: bbb first, then aaa
    // — the submit body should still be sorted (aaa, bbb).
    const cards = screen.getAllByTestId("inline-product-card");
    fireEvent.click(cards[1]!); // bbb
    fireEvent.click(cards[0]!); // aaa
    fireEvent.click(screen.getByTestId("inline-product-next"));
    await waitFor(() => {
      expect(createScanOrderMock).toHaveBeenCalledWith(
        "gd_test",
        {
          length_seconds: 90,
          requested_count: 4,
          time_range_start_ms: 60_000,
          time_range_end_ms: 240_000,
          product_distribution: "multi",
          language: "ko",
          intent: "commit",
          // Sorted client-side to match the server's canonical hash form.
          catalog_entry_ids: [
            SAMPLE_ENTRIES[0]!.catalog_entry_id,
            SAMPLE_ENTRIES[1]!.catalog_entry_id,
          ].sort(),
        },
        expect.any(Function),
      );
    });
    await waitFor(() => {
      expect(onSubmitOrder).toHaveBeenCalledWith(
        "00000000-0000-0000-0000-000000000999",
      );
    });
  });

  it("Next is disabled until a product is selected", async () => {
    triggerEnumerationMock.mockResolvedValue({ job_id: "j1", deduped: false });
    getProductCatalogMock.mockResolvedValue({
      video_id: "gd_test",
      products: SAMPLE_ENTRIES,
      scan_status: "complete",
    });
    renderPanel();
    await waitFor(() => screen.getByTestId("inline-product-grid"));
    const next = screen.getByTestId("inline-product-next") as HTMLButtonElement;
    expect(next.disabled).toBe(true);
    fireEvent.click(screen.getAllByTestId("inline-product-card")[0]!);
    expect(next.disabled).toBe(false);
  });

  it("renders the no-products state when scan_status=complete with empty products", async () => {
    triggerEnumerationMock.mockResolvedValue({ job_id: "j1", deduped: false });
    getProductCatalogMock.mockResolvedValue({
      video_id: "gd_test",
      products: [],
      scan_status: "complete",
    });
    renderPanel();
    await waitFor(() => {
      expect(
        screen.getByTestId("inline-product-no-products"),
      ).toBeInTheDocument();
    });
  });

  it("renders the error state when scan_status=failed", async () => {
    triggerEnumerationMock.mockResolvedValue({ job_id: "j1", deduped: false });
    getProductCatalogMock.mockResolvedValue({
      video_id: "gd_test",
      products: [],
      scan_status: "failed",
    });
    renderPanel();
    await waitFor(() => {
      expect(screen.getByTestId("inline-product-error")).toBeInTheDocument();
    });
    expect(screen.getByTestId("inline-product-retry")).toBeInTheDocument();
  });

  it("Back button fires onBack", async () => {
    triggerEnumerationMock.mockResolvedValue({ job_id: "j1", deduped: false });
    getProductCatalogMock.mockResolvedValue({
      video_id: "gd_test",
      products: [],
      scan_status: "in_progress",
    });
    const { onBack } = renderPanel();
    fireEvent.click(screen.getByTestId("inline-product-back"));
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("normalizes XOR-mismatched time range at submit (belt-and-braces)", async () => {
    // The slider already emits both-or-neither, but if criteria arrives
    // here with one side null and the other set (e.g. a future caller
    // that bypasses the slider, or stale persisted state), the submit
    // path must still produce a backend-valid body. The unmoved side
    // gets backfilled from videoDurationMs (end) or 0 (start).
    triggerEnumerationMock.mockResolvedValue({ job_id: "j1", deduped: false });
    getProductCatalogMock.mockResolvedValue({
      video_id: "gd_test",
      products: SAMPLE_ENTRIES,
      scan_status: "complete",
    });
    createScanOrderMock.mockResolvedValue({
      parent_job_id: "00000000-0000-0000-0000-000000000999",
      run_id: "run-1",
    });
    renderPanel({
      criteria: {
        length_seconds: 60,
        requested_count: 2,
        time_range_start_ms: 60_000,
        time_range_end_ms: null, // ← XOR mismatch
        product_distribution: "single",
      },
    });
    await waitFor(() => screen.getByTestId("inline-product-grid"));
    fireEvent.click(screen.getAllByTestId("inline-product-card")[0]!);
    fireEvent.click(screen.getByTestId("inline-product-next"));
    await waitFor(() => {
      expect(createScanOrderMock).toHaveBeenCalledWith(
        "gd_test",
        expect.objectContaining({
          time_range_start_ms: 60_000,
          time_range_end_ms: FIVE_MIN_MS,
        }),
        expect.any(Function),
      );
    });
  });

  it("summary chip renders distribution + range + length + count", async () => {
    triggerEnumerationMock.mockResolvedValue({ job_id: "j1", deduped: false });
    getProductCatalogMock.mockResolvedValue({
      video_id: "gd_test",
      products: SAMPLE_ENTRIES,
      scan_status: "complete",
    });
    renderPanel({
      criteria: {
        length_seconds: 90,
        requested_count: 4,
        time_range_start_ms: 155_000, // 2:35
        time_range_end_ms: 940_000, // 15:40
        product_distribution: "multi",
      },
    });
    await waitFor(() => screen.getByTestId("inline-product-grid"));
    const chip = screen.getByTestId("inline-product-summary-chip");
    expect(chip.textContent).toContain("통합 쇼츠");
    expect(chip.textContent).toContain("00:02:35 - 00:15:40");
    expect(chip.textContent).toContain("90초 길이");
    expect(chip.textContent).toContain("4개 생성");
  });
});
