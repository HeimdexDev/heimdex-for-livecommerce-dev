"use client";

import { useState } from "react";
import { useImageSelectionContext } from "./ImageSelectionContext";
import { getApiBaseUrl } from "@/lib/api/utils";
import { useAuth } from "@/lib/auth";

export function ImageDownloadBar() {
  const selection = useImageSelectionContext();
  const { getAccessToken } = useAuth();
  const [downloading, setDownloading] = useState(false);

  if (!selection || selection.count === 0) return null;

  const handleDownload = async () => {
    if (downloading) return;
    setDownloading(true);

    try {
      const body = {
        images: selection.selectedItems.map((img) => ({
          video_id: img.videoId,
          scene_id: img.sceneId,
          video_title: img.videoTitle,
        })),
      };

      const headers: Record<string, string> = { "Content-Type": "application/json" };
      const token = await getAccessToken();
      if (token) headers["Authorization"] = `Bearer ${token}`;

      const res = await fetch(`${getApiBaseUrl()}/api/export/images`, {
        method: "POST",
        headers,
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const err = await res.json().catch(() => null);
        throw new Error(err?.detail || `Export failed: ${res.status}`);
      }

      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const fallbackName =
        selection.count === 1 ? "heimdex_image.jpg" : "heimdex_images.zip";
      a.download =
        res.headers.get("Content-Disposition")?.match(/filename="([^"]+)"/)?.[1] ||
        fallbackName;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);

      selection.clear();
    } catch (err) {
      console.error("Image download failed:", err);
      alert(err instanceof Error ? err.message : "Download failed");
    } finally {
      setDownloading(false);
    }
  };

  return (
    <div className="fixed bottom-6 left-1/2 -translate-x-1/2 z-50">
      <div className="flex items-center gap-4 bg-gray-900 text-white px-6 py-3 rounded-full shadow-lg">
        <span className="text-sm font-medium">
          {selection.count}장 선택됨
        </span>

        <button
          onClick={selection.clear}
          className="text-sm text-gray-400 hover:text-white transition-colors"
        >
          초기화
        </button>

        <button
          onClick={handleDownload}
          disabled={downloading}
          className="flex items-center gap-2 bg-primary-600 hover:bg-primary-700 disabled:bg-gray-600 text-white text-sm font-medium px-4 py-1.5 rounded-full transition-colors"
        >
          {downloading ? (
            <>
              <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              다운로드 중...
            </>
          ) : (
            <>
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
              </svg>
              다운로드
            </>
          )}
        </button>
      </div>
    </div>
  );
}
