"use client";

import DashboardContent from "@/components/dashboard/DashboardContent";
import { ImageSelectionProvider } from "@/features/images/ImageSelectionContext";
import { ImageDownloadBar } from "@/features/images/ImageDownloadBar";

export default function ImageSearchContent() {
  return (
    <ImageSelectionProvider>
      <DashboardContent
        defaultContentType="image"
        hideContentTypeToggle
        hideGroupByToggle
        pageSize={60}
      />
      <ImageDownloadBar />
    </ImageSelectionProvider>
  );
}
