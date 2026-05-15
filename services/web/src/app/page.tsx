"use client";

import { Suspense } from "react";
import dynamic from "next/dynamic";

const HomeContent = dynamic(
  () => import("@/components/HomeContent"),
  { ssr: false }
);

export default function Home() {
  return (
    <Suspense>
      <HomeContent />
    </Suspense>
  );
}
