"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { Suspense } from "react";

const RenderViewPage = dynamic(
  () =>
    import("@/features/shorts-render-view/RenderViewPage").then(
      (m) => m.RenderViewPage,
    ),
  { ssr: false },
);

export default function RenderViewRoute() {
  const params = useParams<{ jobId: string }>();
  const jobId = params?.jobId ?? "";
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center">
          <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-indigo-500" />
        </div>
      }
    >
      <RenderViewPage jobId={jobId} />
    </Suspense>
  );
}
