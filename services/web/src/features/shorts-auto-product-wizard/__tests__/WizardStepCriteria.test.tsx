import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { WizardStepCriteria } from "../pages/WizardStepCriteria";

const pushMock = vi.fn();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

describe("WizardStepCriteria", () => {
  beforeEach(() => {
    pushMock.mockReset();
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

  it("navigates to /select-product with criteria as URL params", () => {
    // Phase B: criteria step no longer calls createScanOrder. It just
    // forwards the form values to the product-select step (which then
    // submits with catalog_entry_id baked in).
    render(<WizardStepCriteria videoId="gd_test" />);
    fireEvent.click(screen.getByTestId("length-preset-30"));
    fireEvent.click(screen.getByTestId("count-preset-10"));
    fireEvent.click(screen.getByTestId("language-en"));
    // Both range fields filled: backend XOR-validates the pair, and
    // the criteria step now blocks "다음" when only one side is filled.
    fireEvent.change(screen.getByTestId("range-start-input"), {
      target: { value: "1:30" },
    });
    fireEvent.change(screen.getByTestId("range-end-input"), {
      target: { value: "5:00" },
    });

    fireEvent.click(screen.getByTestId("wizard-next"));

    expect(pushMock).toHaveBeenCalledTimes(1);
    const target = pushMock.mock.calls[0][0] as string;
    // Path is the new step under the same videoId.
    expect(target).toMatch(
      /^\/export\/shorts\/auto\/wizard\/gd_test\/select-product\?/,
    );
    // Query params carry every field the next step needs.
    const url = new URL(`http://x${target}`);
    expect(url.searchParams.get("length")).toBe("30");
    expect(url.searchParams.get("count")).toBe("10");
    expect(url.searchParams.get("language")).toBe("en");
    expect(url.searchParams.get("distribution")).toBe("single");
    expect(url.searchParams.get("intent")).toBe("commit");
    expect(url.searchParams.get("start")).toBe("90000"); // 1:30 → 90 000ms
    expect(url.searchParams.get("end")).toBe("300000"); // 5:00 → 300 000ms
  });

  it("omits start/end params when range fields are blank", () => {
    render(<WizardStepCriteria videoId="gd_test" />);
    fireEvent.click(screen.getByTestId("wizard-next"));
    const target = pushMock.mock.calls[0][0] as string;
    const url = new URL(`http://x${target}`);
    expect(url.searchParams.has("start")).toBe(false);
    expect(url.searchParams.has("end")).toBe(false);
  });

  it("blocks Next + shows warning when only the start range is filled", () => {
    // Backend XOR-validates the time-range pair; surface the rule here
    // so the user fixes it before getting a 422 on the next step.
    render(<WizardStepCriteria videoId="gd_test" />);
    fireEvent.change(screen.getByTestId("range-start-input"), {
      target: { value: "1:30" },
    });
    expect(screen.getByTestId("range-pair-warning")).toBeInTheDocument();
    const next = screen.getByTestId("wizard-next") as HTMLButtonElement;
    expect(next.disabled).toBe(true);
    fireEvent.click(next);
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("blocks Next when only the end range is filled", () => {
    render(<WizardStepCriteria videoId="gd_test" />);
    fireEvent.change(screen.getByTestId("range-end-input"), {
      target: { value: "5:00" },
    });
    expect(screen.getByTestId("range-pair-warning")).toBeInTheDocument();
    const next = screen.getByTestId("wizard-next") as HTMLButtonElement;
    expect(next.disabled).toBe(true);
  });

  it("clears the warning + re-enables Next when the missing side is filled", () => {
    render(<WizardStepCriteria videoId="gd_test" />);
    fireEvent.change(screen.getByTestId("range-start-input"), {
      target: { value: "1:30" },
    });
    expect(screen.getByTestId("range-pair-warning")).toBeInTheDocument();
    fireEvent.change(screen.getByTestId("range-end-input"), {
      target: { value: "5:00" },
    });
    expect(
      screen.queryByTestId("range-pair-warning"),
    ).not.toBeInTheDocument();
    const next = screen.getByTestId("wizard-next") as HTMLButtonElement;
    expect(next.disabled).toBe(false);
  });
});
