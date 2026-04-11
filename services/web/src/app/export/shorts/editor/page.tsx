"use client";

import dynamic from "next/dynamic";
import { Suspense } from "react";

const ShortsEditorPage = dynamic(
  () =>
    import("@/features/shorts-editor/components/ShortsEditorPage").then(
      (m) => m.ShortsEditorPage,
    ),
  { ssr: false },
);

export default function EditorRoute() {
  return (
    <Suspense
      fallback={
        <div className="flex min-h-screen items-center justify-center">
          <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-indigo-500" />
        </div>
      }
    >
      <ShortsEditorPage />
    </Suspense>
  );
}
