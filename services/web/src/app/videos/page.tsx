"use client";

import dynamic from "next/dynamic";

const VideosContent = dynamic(
  () => import("@/features/videos").then((mod) => ({ default: mod.VideosContainer })),
  { ssr: false },
);

export default function VideosPage() {
  return <VideosContent />;
}
