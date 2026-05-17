"use client";

import { useState } from "react";
import {
  generateHighlightPreview,
  type HighlightReelPreviewResponse,
} from "@/lib/api/highlight-reel";

const DURATION_OPTIONS = [
  { label: "30초", value: 30 },
  { label: "1분", value: 60 },
  { label: "2분", value: 120 },
  { label: "3분", value: 180 },
  { label: "5분", value: 300 },
] as const;

interface HighlightReelButtonProps {
  personClusterId: string;
  getToken: () => Promise<string | null>;
  onPreviewReady: (preview: HighlightReelPreviewResponse) => void;
}

export function HighlightReelButton({
  personClusterId,
  getToken,
  onPreviewReady,
}: HighlightReelButtonProps) {
  const [duration, setDuration] = useState(60);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = async () => {
    setLoading(true);
    setError(null);
    try {
      const preview = await generateHighlightPreview(personClusterId, duration, getToken);
      onPreviewReady(preview);
    } catch (err) {
      setError(err instanceof Error ? err.message : "생성에 실패했습니다.");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2">
        <select
          value={duration}
          onChange={(e) => setDuration(Number(e.target.value))}
          disabled={loading}
          className="rounded border border-gray-200 px-2 py-1.5 text-sm text-gray-700 focus:border-indigo-400 focus:outline-none focus:ring-1 focus:ring-indigo-400"
        >
          {DURATION_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
        <button
          type="button"
          onClick={handleGenerate}
          disabled={loading}
          className="flex flex-1 items-center justify-center gap-1.5 rounded-md bg-indigo-500 px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-indigo-600 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {loading ? (
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-white border-t-transparent" />
          ) : (
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" d="m15.75 10.5 4.72-4.72a.75.75 0 0 1 1.28.53v11.38a.75.75 0 0 1-1.28.53l-4.72-4.72M4.5 18.75h9a2.25 2.25 0 0 0 2.25-2.25v-9a2.25 2.25 0 0 0-2.25-2.25h-9A2.25 2.25 0 0 0 2.25 7.5v9a2.25 2.25 0 0 0 2.25 2.25Z" /></svg>
          )}
          {loading ? "생성 중..." : "하이라이트 릴"}
        </button>
      </div>
      {error && (
        <p className="text-xs text-red-500">{error}</p>
      )}
    </div>
  );
}
