"use client";

import { Suspense } from "react";
import dynamic from "next/dynamic";

const ShortsCreate = dynamic(
  () => import("@/features/shorts").then((mod) => ({ default: mod.ShortsCreatePage })),
  { ssr: false },
);

function LoadingFallback() {
  return (
    <div className="flex min-h-[400px] items-center justify-center">
      <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-indigo-500" />
    </div>
  );
}

export default function ShortsCreatePage() {
  return (
    <Suspense fallback={<LoadingFallback />}>
      <ShortsCreate />
    </Suspense>
  );
}
