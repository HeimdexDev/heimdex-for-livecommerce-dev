"use client";

import { Suspense } from "react";
import dynamic from "next/dynamic";

const ImageSearchContent = dynamic(
  () => import("@/components/ImageSearchContent"),
  { ssr: false }
);

export default function ImageSearchPage() {
  return (
    <Suspense>
      <ImageSearchContent />
    </Suspense>
  );
}
