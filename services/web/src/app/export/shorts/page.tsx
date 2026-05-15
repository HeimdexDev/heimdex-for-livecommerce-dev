"use client";

import dynamic from "next/dynamic";

const SavedShorts = dynamic(
  () => import("@/features/shorts").then((mod) => ({ default: mod.SavedShortsPage })),
  { ssr: false },
);

export default function ShortsPage() {
  return <SavedShorts />;
}
