"use client";

import { formatTimestamp } from "@/lib/api/utils";
import { getAgentPlaybackUrl, getCloudPlaybackUrl } from "@/lib/agent";
import { cn } from "@/lib/utils";
import type { ShortsCandidateResponse } from "@/lib/types";
import { FEATURES } from "@/lib/feature-flags";

interface CandidateCardProps {
  candidate: ShortsCandidateResponse;
  rank: number;
  isSelected: boolean;
  onToggle: () => void;
  agentAvailable: boolean;
  videoId: string;
}

export function CandidateCard({
  candidate,
  rank,
  isSelected,
  onToggle,
  agentAvailable,
  videoId,
}: CandidateCardProps) {
  return (
    <div
      className={cn(
        "p-3 rounded-lg border hover:border-gray-200 transition-colors",
        isSelected ? "border-primary-200 bg-primary-50/30" : "border-gray-100",
      )}
    >
      <div className="flex items-start gap-3">
        <input
          type="checkbox"
          checked={isSelected}
          onChange={onToggle}
          className="mt-1 h-4 w-4 rounded border-gray-300 text-primary-600 focus:ring-primary-500"
          aria-label={`Select ${candidate.title_suggestion}`}
        />

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-xs font-semibold text-gray-500">#{rank}</span>
            <span className="text-xs font-semibold text-amber-600">★ {candidate.score.toFixed(2)}</span>
            <p className="text-sm font-semibold text-gray-900 truncate">{candidate.title_suggestion}</p>
          </div>

          <div className="mt-1 flex flex-wrap items-center gap-1.5">
            <span className="font-mono text-xs text-gray-500">
              {formatTimestamp(candidate.start_ms)} - {formatTimestamp(candidate.end_ms)}
            </span>
            {FEATURES.TAGS_ENABLED && candidate.tags.map((tag) => (
              <span
                key={tag}
                className="inline-block px-1.5 py-0.5 text-xs bg-blue-50 text-blue-700 rounded"
              >
                {tag}
              </span>
            ))}
          </div>

          <p className="mt-1.5 text-sm text-gray-700 line-clamp-2">{candidate.transcript_snippet}</p>

          <div className="mt-2 flex items-center justify-between gap-2">
            <button
              type="button"
              className={cn(
                "text-sm flex items-center gap-1 px-2 py-1 rounded-md border",
                agentAvailable
                  ? "text-primary-600 hover:bg-primary-50 border-primary-200 cursor-pointer"
                  : "text-gray-400 border-gray-200 cursor-not-allowed",
              )}
              disabled={!agentAvailable}
              onClick={() => {
                if (agentAvailable) {
                  const url = videoId.startsWith("gd_")
                    ? getCloudPlaybackUrl(videoId, candidate.start_ms)
                    : getAgentPlaybackUrl(videoId, candidate.start_ms);
                  window.open(url, "_blank");
                }
              }}
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z"
                />
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"
                />
              </svg>
              Play
            </button>

            <p className="text-xs text-gray-500 text-right">
              Products: {candidate.product_refs.join(", ") || "-"} | People: {candidate.people_refs.join(", ") || "-"}
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
