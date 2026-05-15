"use client";

import dynamic from "next/dynamic";
import { Suspense } from "react";

// Lazy-loaded for parity with the existing video detail route, so the
// blur bundle doesn't ship on the main video browse path.
const BlurDetail = dynamic(
  () =>
    import("@/features/blur/components/BlurDetailPage").then((mod) => ({
      default: mod.BlurDetailPage,
    })),
  { ssr: false },
);

export default function BlurDetailRoute({
  params,
}: {
  params: { videoId: string };
}) {
  return (
    <Suspense>
      <BlurDetail videoId={params.videoId} />
    </Suspense>
  );
}
