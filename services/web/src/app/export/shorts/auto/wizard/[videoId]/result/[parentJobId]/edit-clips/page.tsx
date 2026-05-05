"use client";

import dynamic from "next/dynamic";
import { useParams } from "next/navigation";
import { Suspense } from "react";

const EditClipsPage = dynamic(
  () =>
    import("@/features/shorts-auto-product-wizard/pages/EditClipsPage").then(
      (m) => m.EditClipsPage,
    ),
  { ssr: false },
);

export default function EditClipsRoute() {
  const params = useParams<{ videoId: string; parentJobId: string }>();
  const videoId = params?.videoId ?? "";
  const parentJobId = params?.parentJobId ?? "";
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center">
          <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-indigo-500" />
        </div>
      }
    >
      <EditClipsPage videoId={videoId} parentJobId={parentJobId} />
    </Suspense>
  );
}
