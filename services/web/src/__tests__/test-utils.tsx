import { render, type RenderOptions } from "@testing-library/react";
import { SceneBasketProvider } from "@/features/basket/useSceneBasket";
import { OrgSettingsProvider } from "@/lib/orgSettings";
import type { ReactElement, ReactNode } from "react";

function AllProviders({ children }: { children: ReactNode }) {
  return (
    <OrgSettingsProvider>
      <SceneBasketProvider>{children}</SceneBasketProvider>
    </OrgSettingsProvider>
  );
}

/**
 * Renders a component wrapped in all required context providers.
 * Use instead of plain render() when the component (or any child)
 * calls useSceneBasket().
 */
export function renderWithProviders(
  ui: ReactElement,
  options?: Omit<RenderOptions, "wrapper">,
) {
  return render(ui, { wrapper: AllProviders, ...options });
}

export * from "@testing-library/react";
export { renderWithProviders as render };
