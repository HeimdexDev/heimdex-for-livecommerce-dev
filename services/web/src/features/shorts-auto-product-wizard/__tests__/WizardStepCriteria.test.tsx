import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { WizardStepCriteria } from "../pages/WizardStepCriteria";

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ getAccessToken: vi.fn(async () => "test-token") }),
}));

const createScanOrderMock = vi.fn();
vi.mock("@/lib/api/shorts-auto-product-wizard", async () => {
  const actual = await vi.importActual<
    typeof import("@/lib/api/shorts-auto-product-wizard")
  >("@/lib/api/shorts-auto-product-wizard");
  return {
    ...actual,
    createScanOrder: (...args: unknown[]) => createScanOrderMock(...args),
  };
});

describe("WizardStepCriteria", () => {
  beforeEach(() => {
    pushMock.mockReset();
    createScanOrderMock.mockReset();
  });

  it("renders all five inputs with sensible defaults", () => {
    render(<WizardStepCriteria videoId="gd_test" />);
    expect(screen.getByTestId("length-preset-60")).toBeInTheDocument();
    expect(screen.getByTestId("count-preset-5")).toBeInTheDocument();
    expect(screen.getByTestId("range-start-input")).toBeInTheDocument();
    expect(screen.getByTestId("range-end-input")).toBeInTheDocument();
    expect(screen.getByTestId("distribution-single")).toBeInTheDocument();
    expect(screen.getByTestId("language-ko")).toBeInTheDocument();
  });

  it("shows the aggregate-cap warning when count × length > 1800s", () => {
    render(<WizardStepCriteria videoId="gd_test" />);
    // default 60s × 5 = 300s — no warning yet
    expect(
      screen.queryByTestId("aggregate-cap-warning"),
    ).not.toBeInTheDocument();
    // bump count → 60s × 20 = 1200 (still ok)
    fireEvent.click(screen.getByTestId("count-preset-20"));
    expect(
      screen.queryByTestId("aggregate-cap-warning"),
    ).not.toBeInTheDocument();
    // bump length to 120 → 120 × 20 = 2400, over cap
    fireEvent.click(screen.getByTestId("length-preset-120"));
    expect(screen.getByTestId("aggregate-cap-warning")).toBeInTheDocument();
  });

  it("disables Next when over the aggregate cap", () => {
    render(<WizardStepCriteria videoId="gd_test" />);
    fireEvent.click(screen.getByTestId("count-preset-20"));
    fireEvent.click(screen.getByTestId("length-preset-120"));
    const next = screen.getByTestId("wizard-next") as HTMLButtonElement;
    expect(next.disabled).toBe(true);
  });

  it("submits the scan order with the chosen criteria + routes to step 4", async () => {
    createScanOrderMock.mockResolvedValueOnce({
      parent_job_id: "00000000-0000-0000-0000-000000000123",
      deduped: false,
    });
    render(<WizardStepCriteria videoId="gd_test" />);
    fireEvent.click(screen.getByTestId("length-preset-30"));
    fireEvent.click(screen.getByTestId("count-preset-10"));
    fireEvent.click(screen.getByTestId("language-en"));
    fireEvent.change(screen.getByTestId("range-start-input"), {
      target: { value: "1:30" },
    });

    fireEvent.click(screen.getByTestId("wizard-next"));

    await waitFor(() => expect(createScanOrderMock).toHaveBeenCalledTimes(1));
    expect(createScanOrderMock.mock.calls[0][0]).toBe("gd_test");
    const body = createScanOrderMock.mock.calls[0][1];
    expect(body).toMatchObject({
      length_seconds: 30,
      requested_count: 10,
      language: "en",
      product_distribution: "single",
      intent: "commit",
      time_range_start_ms: 90_000, // 1:30 = 90s = 90000ms
    });
    await waitFor(() =>
      expect(pushMock).toHaveBeenCalledWith(
        "/export/shorts/auto/wizard/gd_test/result/00000000-0000-0000-0000-000000000123",
      ),
    );
  });

  it("surfaces the API's 422 detail message", async () => {
    const { WizardValidationError } = await import(
      "@/lib/api/shorts-auto-product-wizard"
    );
    createScanOrderMock.mockRejectedValueOnce(
      new WizardValidationError("requested_count must be >= 1"),
    );
    render(<WizardStepCriteria videoId="gd_test" />);
    fireEvent.click(screen.getByTestId("wizard-next"));
    const error = await screen.findByTestId("error-message");
    expect(error.textContent).toContain("requested_count must be >= 1");
    expect(pushMock).not.toHaveBeenCalled();
  });
});
