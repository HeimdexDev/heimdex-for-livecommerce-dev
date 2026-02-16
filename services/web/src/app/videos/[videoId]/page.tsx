"use client";

import dynamic from "next/dynamic";

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
  return <VideoDetail videoId={params.videoId} />;
}
