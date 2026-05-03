"use client";

import dynamic from "next/dynamic";
import { Suspense } from "react";

const WizardStepVideoSelect = dynamic(
  () =>
    import("@/features/shorts-auto-product-wizard/pages/WizardStepVideoSelect").then(
      (m) => m.WizardStepVideoSelect,
    ),
  { ssr: false },
);

export default function WizardEntryRoute() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center">
          <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-indigo-500" />
        </div>
      }
    >
      <WizardStepVideoSelect />
    </Suspense>
  );
}
