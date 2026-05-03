"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { Suspense } from "react";

const WizardStepSelectProduct = dynamic(
  () =>
    import(
      "@/features/shorts-auto-product-wizard/pages/WizardStepSelectProduct"
    ).then((m) => m.WizardStepSelectProduct),
  { ssr: false },
);

export default function WizardSelectProductRoute() {
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
      <WizardStepSelectProduct videoId={videoId} />
    </Suspense>
  );
}
