"use client";

import dynamic from "next/dynamic";
import { Suspense } from "react";

const VideoDetail = dynamic(
  () =>
    import("@/features/videos/components/VideoDetailPage").then((mod) => ({
      default: mod.VideoDetailPage,
    })),
  { ssr: false },
);

export default function VideoDetailRoute({
  params,
}: {
  params: { videoId: string };
}) {
  return <Suspense><VideoDetail videoId={params.videoId} /></Suspense>;
}
