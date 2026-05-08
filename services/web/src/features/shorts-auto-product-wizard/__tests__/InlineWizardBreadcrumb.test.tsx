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

  it("uses gray-900 background only on the active circle", () => {
    render(<InlineWizardBreadcrumb currentStep={2} />);
    const active = screen.getByTestId("inline-wizard-breadcrumb-step-2-circle");
    const upcoming = screen.getByTestId(
      "inline-wizard-breadcrumb-step-3-circle",
    );
    expect(active.className).toMatch(/bg-gray-900/);
    expect(upcoming.className).not.toMatch(/bg-gray-900/);
  });

  it("renders divider chevrons between steps but not after the last", () => {
    const { container } = render(<InlineWizardBreadcrumb currentStep={1} />);
    const chevrons = container.querySelectorAll("[aria-hidden='true']");
    expect(chevrons).toHaveLength(2);
  });
});
