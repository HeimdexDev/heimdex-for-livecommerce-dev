"use client";

import dynamic from "next/dynamic";

const PreeditPage = dynamic(
  () => import("@/features/preedit").then((m) => ({ default: m.PreeditPage })),
  { ssr: false },
);

export default function Page() {
  return <PreeditPage />;
}
