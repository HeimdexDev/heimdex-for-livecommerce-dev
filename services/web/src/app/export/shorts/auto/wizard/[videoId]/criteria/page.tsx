"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { Suspense } from "react";

const WizardStepCriteria = dynamic(
  () =>
    import("@/features/shorts-auto-product-wizard/pages/WizardStepCriteria").then(
      (m) => m.WizardStepCriteria,
    ),
  { ssr: false },
);

export default function WizardCriteriaRoute() {
  const params = useParams<{ videoId: string }>();
  const videoId = params?.videoId ?? "";
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center">
          <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-indigo-500" />
        </div>
      }
    >
      <WizardStepCriteria videoId={videoId} />
    </Suspense>
  );
}
