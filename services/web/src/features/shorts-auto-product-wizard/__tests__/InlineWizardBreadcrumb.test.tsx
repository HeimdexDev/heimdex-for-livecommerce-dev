import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

import { InlineWizardBreadcrumb } from "../components/InlineWizardBreadcrumb";

describe("InlineWizardBreadcrumb", () => {
  it("renders three labelled steps", () => {
    render(<InlineWizardBreadcrumb currentStep={1} />);
    expect(screen.getByText("옵션 설정")).toBeInTheDocument();
    expect(screen.getByText("상품 선택")).toBeInTheDocument();
    expect(screen.getByText("AI 쇼츠 생성")).toBeInTheDocument();
  });

  it("marks only the current step as active", () => {
    render(<InlineWizardBreadcrumb currentStep={2} />);
    const c1 = screen.getByTestId("inline-wizard-breadcrumb-step-1-circle");
    const c2 = screen.getByTestId("inline-wizard-breadcrumb-step-2-circle");
    const c3 = screen.getByTestId("inline-wizard-breadcrumb-step-3-circle");
    expect(c1.dataset.active).toBe("false");
    expect(c2.dataset.active).toBe("true");
    expect(c3.dataset.active).toBe("false");
  });

  it("uses heimdex-navy-500 background only on the active circle", () => {
    render(<InlineWizardBreadcrumb currentStep={2} />);
    const active = screen.getByTestId("inline-wizard-breadcrumb-step-2-circle");
    const upcoming = screen.getByTestId(
      "inline-wizard-breadcrumb-step-3-circle",
    );
    expect(active.className).toMatch(/bg-heimdex-navy-500/);
    expect(upcoming.className).not.toMatch(/bg-heimdex-navy-500/);
  });

  it("renders divider chevrons between steps but not after the last", () => {
    const { container } = render(<InlineWizardBreadcrumb currentStep={1} />);
    const chevrons = container.querySelectorAll("[aria-hidden='true']");
    expect(chevrons).toHaveLength(2);
  });
});

describe("InlineWizardBreadcrumb — two-step variant", () => {
  it("renders only two labelled steps (옵션 설정, AI 쇼츠 생성)", () => {
    render(
      <InlineWizardBreadcrumb variant="two-step" currentStep={1} />,
    );
    expect(screen.getByText("옵션 설정")).toBeInTheDocument();
    expect(screen.getByText("AI 쇼츠 생성")).toBeInTheDocument();
    expect(screen.queryByText("상품 선택")).not.toBeInTheDocument();
    expect(
      screen.queryByTestId("inline-wizard-breadcrumb-step-3-circle"),
    ).not.toBeInTheDocument();
  });

  it("marks only the current step as active", () => {
    render(
      <InlineWizardBreadcrumb variant="two-step" currentStep={2} />,
    );
    const c1 = screen.getByTestId("inline-wizard-breadcrumb-step-1-circle");
    const c2 = screen.getByTestId("inline-wizard-breadcrumb-step-2-circle");
    expect(c1.dataset.active).toBe("false");
    expect(c2.dataset.active).toBe("true");
  });

  it("uses heimdex-navy-500 background only on the active circle", () => {
    render(
      <InlineWizardBreadcrumb variant="two-step" currentStep={2} />,
    );
    const active = screen.getByTestId("inline-wizard-breadcrumb-step-2-circle");
    const upcoming = screen.getByTestId(
      "inline-wizard-breadcrumb-step-1-circle",
    );
    expect(active.className).toMatch(/bg-heimdex-navy-500/);
    expect(upcoming.className).not.toMatch(/bg-heimdex-navy-500/);
  });

  it("renders exactly one chevron between the two steps", () => {
    const { container } = render(
      <InlineWizardBreadcrumb variant="two-step" currentStep={1} />,
    );
    const chevrons = container.querySelectorAll("[aria-hidden='true']");
    expect(chevrons).toHaveLength(1);
  });

  it("exposes the variant on the root for downstream styling/testing", () => {
    render(
      <InlineWizardBreadcrumb variant="two-step" currentStep={2} />,
    );
    expect(
      screen.getByTestId("inline-wizard-breadcrumb").dataset.variant,
    ).toBe("two-step");
  });
});
