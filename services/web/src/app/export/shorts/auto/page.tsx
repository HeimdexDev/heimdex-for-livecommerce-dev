"use client";

import dynamic from "next/dynamic";
import { Suspense } from "react";

const AutoShortsPage = dynamic(
  () => import("@/features/shorts-auto").then((m) => m.AutoShortsPage),
  { ssr: false },
);

export default function AutoShortsRoute() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center">
          <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-indigo-500" />
        </div>
      }
    >
      <AutoShortsPage />
    </Suspense>
  );
}
