"use client";

import { SegmentResult, formatDuration } from "@/lib/api";
import { cn } from "@/lib/utils";
import { useState } from "react";

interface SearchResultsProps {
  results: SegmentResult[];
  totalCandidates: number;
  showDebug: boolean;
}

export function SearchResults({
  results,
  totalCandidates,
  showDebug,
}: SearchResultsProps) {
  if (results.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        <p>No results found. Try a different search query.</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between text-sm text-gray-600">
        <span>
          Showing {results.length} of {totalCandidates} candidates
        </span>
      </div>

      <div className="space-y-3">
        {results.map((result, index) => (
          <ResultCard
            key={result.segment_id}
            result={result}
            rank={index + 1}
            showDebug={showDebug}
          />
        ))}
      </div>
    </div>
  );
}

interface ResultCardProps {
  result: SegmentResult;
  rank: number;
  showDebug: boolean;
}

function ResultCard({ result, rank, showDebug }: ResultCardProps) {
  const [expanded, setExpanded] = useState(false);
  const isRemovable = result.source_type === "removable_disk";

  return (
    <div className="card p-4 hover:shadow-md transition-shadow">
      <div className="flex gap-4">
        <div className="flex-shrink-0 relative">
          <div className="w-32 h-20 bg-gray-200 rounded-lg overflow-hidden">
            {result.thumbnail_url ? (
              <img
                src={result.thumbnail_url}
                alt="Thumbnail"
                className="w-full h-full object-cover"
                onError={(e) => {
                  (e.target as HTMLImageElement).style.display = "none";
                }}
              />
            ) : (
              <div className="w-full h-full flex items-center justify-center text-gray-400">
                <svg
                  className="w-8 h-8"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M15 10l4.553-2.276A1 1 0 0121 8.618v6.764a1 1 0 01-1.447.894L15 14M5 18h8a2 2 0 002-2V8a2 2 0 00-2-2H5a2 2 0 00-2 2v8a2 2 0 002 2z"
                  />
                </svg>
              </div>
            )}
          </div>
          <span className="absolute -top-2 -left-2 bg-primary-600 text-white text-xs font-bold w-6 h-6 rounded-full flex items-center justify-center">
            {rank}
          </span>
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2 mb-1">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-gray-900 truncate">
                {result.library_name}
              </span>
              <span
                className={cn(
                  "px-2 py-0.5 rounded-full text-xs font-medium",
                  result.source_type === "gdrive"
                    ? "bg-blue-100 text-blue-700"
                    : "bg-orange-100 text-orange-700"
                )}
              >
                {result.source_type === "gdrive" ? "Drive" : "Local"}
              </span>
            </div>
            <span className="text-xs text-gray-500 whitespace-nowrap">
              {formatDuration(result.start_ms, result.end_ms)}
            </span>
          </div>

          <p className="text-sm text-gray-700 line-clamp-2 mb-2">
            {result.snippet}
          </p>

          <div className="flex items-center gap-3">
            <button
              className="text-sm text-gray-400 cursor-not-allowed flex items-center gap-1"
              disabled
              title="Playback requires the Heimdex agent running on this machine"
            >
              <svg
                className="w-4 h-4"
                fill="none"
                viewBox="0 0 24 24"
                stroke="currentColor"
              >
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
              Play (Not available)
            </button>

            {isRemovable && result.required_drive_nickname && (
              <span className="text-xs text-orange-600 flex items-center gap-1">
                <svg
                  className="w-4 h-4"
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path
                    strokeLinecap="round"
                    strokeLinejoin="round"
                    strokeWidth={2}
                    d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8m-9 4h4"
                  />
                </svg>
                Requires: {result.required_drive_nickname}
              </span>
            )}

            {result.people_cluster_ids.length > 0 && (
              <span className="text-xs text-gray-500">
                {result.people_cluster_ids.length} people detected
              </span>
            )}
          </div>
        </div>
      </div>

      {showDebug && (
        <div className="mt-3 pt-3 border-t border-gray-100">
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-gray-500 hover:text-gray-700 flex items-center gap-1"
          >
            <svg
              className={cn("w-3 h-3 transition-transform", expanded && "rotate-90")}
              fill="none"
              viewBox="0 0 24 24"
              stroke="currentColor"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M9 5l7 7-7 7"
              />
            </svg>
            Debug Info
          </button>

          {expanded && <DebugPanel debug={result.debug} />}
        </div>
      )}
    </div>
  );
}

function DebugPanel({ debug }: { debug: SegmentResult["debug"] }) {
  return (
    <div className="mt-2 p-3 bg-gray-50 rounded-lg text-xs font-mono">
      <div className="grid grid-cols-2 gap-2">
        <div>
          <span className="text-gray-500">Lexical Rank:</span>{" "}
          <span className="text-gray-900">
            {debug.lexical_rank ?? "N/A"}
          </span>
        </div>
        <div>
          <span className="text-gray-500">Lexical Score:</span>{" "}
          <span className="text-gray-900">
            {debug.lexical_score?.toFixed(3) ?? "N/A"}
          </span>
        </div>
        <div>
          <span className="text-gray-500">Vector Rank:</span>{" "}
          <span className="text-gray-900">
            {debug.vector_rank ?? "N/A"}
          </span>
        </div>
        <div>
          <span className="text-gray-500">Vector Score:</span>{" "}
          <span className="text-gray-900">
            {debug.vector_score?.toFixed(3) ?? "N/A"}
          </span>
        </div>
        <div>
          <span className="text-gray-500">Lexical Contribution:</span>{" "}
          <span className="text-gray-900">
            {debug.lexical_contribution.toFixed(4)}
          </span>
        </div>
        <div>
          <span className="text-gray-500">Vector Contribution:</span>{" "}
          <span className="text-gray-900">
            {debug.vector_contribution.toFixed(4)}
          </span>
        </div>
        <div>
          <span className="text-gray-500">Fused Score:</span>{" "}
          <span className="text-gray-900">
            {debug.fused_score.toFixed(6)}
          </span>
        </div>
        <div>
          <span className="text-gray-500">Quality Factor:</span>{" "}
          <span className="text-gray-900">
            {debug.quality_factor.toFixed(2)}
          </span>
        </div>
        <div className="col-span-2">
          <span className="text-gray-500">Adjusted Score:</span>{" "}
          <span className="text-primary-600 font-semibold">
            {debug.adjusted_score.toFixed(6)}
          </span>
          {debug.diversification_penalty && (
            <span className="ml-2 px-1.5 py-0.5 bg-yellow-100 text-yellow-800 rounded text-[10px]">
              diversified
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
