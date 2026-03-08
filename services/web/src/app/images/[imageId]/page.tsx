"use client";

import dynamic from "next/dynamic";
import { Suspense } from "react";

const ImageDetail = dynamic(
  () =>
    import("@/features/images/ImageDetailPage").then((mod) => ({
      default: mod.ImageDetailPage,
    })),
  { ssr: false },
);

export default function ImageDetailRoute({
  params,
}: {
  params: { imageId: string };
}) {
  return <Suspense><ImageDetail imageId={params.imageId} /></Suspense>;
}
