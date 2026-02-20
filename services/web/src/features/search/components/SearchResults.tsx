"use client";

import {
  SegmentResult,
  SceneResult,
  AnySearchResponse,
  DebugInfo,
  formatDuration,
} from "@/lib/api";
import { getAgentPlaybackUrl, getCloudPlaybackUrl } from "@/lib/agent";
import { SceneThumbnail } from "@/components/SceneThumbnail";
import { cn } from "@/lib/utils";
import { useState } from "react";

function playbackUrl(videoId: string, sourceType: string, startMs?: number): string {
  return sourceType === "gdrive"
    ? getCloudPlaybackUrl(videoId, startMs)
    : getAgentPlaybackUrl(videoId, startMs);
}

// ============================================================================
// Helpers
// ============================================================================

function getMatchSignal(debug: DebugInfo): { label: string; color: string } {
  const total = debug.lexical_contribution + debug.vector_contribution;
  if (total === 0) return { label: "No signal", color: "bg-gray-100 text-gray-600" };

  if (debug.ocr_contribution && debug.ocr_contribution / total > 0.7) {
    return { label: "On-screen match", color: "bg-orange-100 text-orange-700" };
  }

  const lexicalPct = debug.lexical_contribution / total;
  if (lexicalPct > 0.7) return { label: "Keyword match", color: "bg-green-100 text-green-700" };
  if (lexicalPct < 0.3) return { label: "Semantic match", color: "bg-purple-100 text-purple-700" };
  return { label: "Hybrid match", color: "bg-blue-100 text-blue-700" };
}

function getQualityColor(qf: number): string {
  if (qf < 0.8) return "bg-red-400";
  if (qf < 0.95) return "bg-yellow-400";
  return "bg-green-400";
}

interface VideoGroup {
  videoId: string;
  videoTitle: string | null;
  libraryName: string;
  sourceType: "gdrive" | "removable_disk" | "local";
  scenes: SceneResult[];
}

function groupScenesByVideo(scenes: SceneResult[]): VideoGroup[] {
  const map = new Map<string, VideoGroup>();
  for (const scene of scenes) {
    let group = map.get(scene.video_id);
    if (!group) {
      group = {
        videoId: scene.video_id,
        videoTitle: scene.video_title,
        libraryName: scene.library_name,
        sourceType: scene.source_type,
        scenes: [],
      };
      map.set(scene.video_id, group);
    }
    group.scenes.push(scene);
  }
  const groups = Array.from(map.values());
  for (const group of groups) {
    group.scenes.sort((a: SceneResult, b: SceneResult) => a.start_ms - b.start_ms);
  }
  return groups;
}

function sourceTypeLabel(sourceType: string): string {
  return sourceType === "gdrive" ? "Drive" : sourceType === "removable_disk" ? "Disk" : "Local";
}

function sourceTypeBadgeClass(sourceType: string): string {
  return sourceType === "gdrive"
    ? "bg-blue-100 text-blue-700"
    : sourceType === "removable_disk"
    ? "bg-orange-100 text-orange-700"
    : "bg-green-100 text-green-700";
}

function Breadcrumb({ libraryName, sourceType }: { libraryName: string; sourceType: string }) {
  const [open, setOpen] = useState(false);
  return (
    <span className="inline-flex items-center gap-1 text-xs text-gray-400">
      <span
        role="button"
        tabIndex={0}
        onClick={(e) => { e.stopPropagation(); setOpen(!open); }}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.stopPropagation(); setOpen(!open); } }}
        className="hover:text-gray-600 transition-colors flex items-center gap-0.5 cursor-pointer"
        title={open ? "Hide location" : `${libraryName} \u203A ${sourceTypeLabel(sourceType)}`}
      >
        <svg
          className={cn("w-3 h-3 transition-transform", open && "rotate-90")}
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
        >
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
        <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
        </svg>
      </span>
      {open && (
        <span className="text-gray-500">
          {libraryName}
          <span className="mx-1 text-gray-300">&rsaquo;</span>
          <span className={cn("px-1.5 py-0 rounded text-[10px] font-medium", sourceTypeBadgeClass(sourceType))}>
            {sourceTypeLabel(sourceType)}
          </span>
        </span>
      )}
    </span>
  );
}

// ============================================================================
// SearchResults — main export
// ============================================================================

interface SearchResultsProps {
  response: AnySearchResponse;
  showDebug: boolean;
  agentAvailable: boolean;
}

export function SearchResults({
  response,
  showDebug,
  agentAvailable,
}: SearchResultsProps) {
  if (response.results.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        <p>No results found. Try a different search query.</p>
      </div>
    );
  }

  const isScene = response.result_type === "scene";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between text-sm text-gray-600">
        <span>
          Showing {response.results.length} of {response.total_candidates} candidates
        </span>
        {isScene && (
          <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-purple-100 text-purple-700">
            Scene results
          </span>
        )}
      </div>

      <div className="space-y-3">
        {isScene ? (
          <VideoGroupList
            groups={groupScenesByVideo(response.results as SceneResult[])}
            showDebug={showDebug}
            agentAvailable={agentAvailable}
          />
        ) : (
          (response.results as SegmentResult[]).map((result, index) => (
            <ResultCard
              key={result.segment_id}
              result={result}
              rank={index + 1}
              showDebug={showDebug}
              agentAvailable={agentAvailable}
            />
          ))
        )}
      </div>
    </div>
  );
}

// ============================================================================
// VideoGroupList — groups scenes by video with collapse/expand
// ============================================================================

function VideoGroupList({
  groups,
  showDebug,
  agentAvailable,
}: {
  groups: VideoGroup[];
  showDebug: boolean;
  agentAvailable: boolean;
}) {
  const [expandedVideos, setExpandedVideos] = useState<Set<string>>(
    () => new Set(groups.length > 0 ? [groups[0].videoId] : [])
  );

  const toggleVideo = (videoId: string) => {
    setExpandedVideos((prev) => {
      const next = new Set(prev);
      if (next.has(videoId)) {
        next.delete(videoId);
      } else {
        next.add(videoId);
      }
      return next;
    });
  };

  let globalRank = 0;

  return (
    <div className="space-y-4">
      {groups.map((group) => {
        const isExpanded = expandedVideos.has(group.videoId);
        return (
          <div key={group.videoId} className="border border-gray-200 rounded-lg overflow-hidden">
            <button
              onClick={() => toggleVideo(group.videoId)}
              className="w-full flex items-center justify-between px-4 py-3 bg-gray-50 hover:bg-gray-100 transition-colors text-left"
            >
              <div className="flex items-center gap-2 min-w-0">
                <svg
                  className={cn("w-4 h-4 text-gray-500 transition-transform flex-shrink-0", isExpanded && "rotate-90")}
                  fill="none"
                  viewBox="0 0 24 24"
                  stroke="currentColor"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
                <span className="text-sm font-medium text-gray-900 truncate">
                  {group.videoTitle || group.videoId}
                </span>
                <Breadcrumb libraryName={group.libraryName} sourceType={group.sourceType} />
              </div>
              <span className="text-xs text-gray-500 flex-shrink-0 ml-2">
                {group.scenes.length} scene{group.scenes.length !== 1 ? "s" : ""}
              </span>
            </button>

            {isExpanded && (
              <div className="divide-y divide-gray-100">
                {group.scenes.map((scene) => {
                  globalRank++;
                  return (
                    <SceneCard
                      key={scene.scene_id}
                      result={scene}
                      rank={globalRank}
                      showDebug={showDebug}
                      agentAvailable={agentAvailable}
                    />
                  );
                })}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ============================================================================
// SceneCard — match signal, quality indicator, context play
// ============================================================================

interface SceneCardProps {
  result: SceneResult;
  rank: number;
  showDebug: boolean;
  agentAvailable: boolean;
}

function SceneCard({ result, rank, showDebug, agentAvailable }: SceneCardProps) {
  const [expanded, setExpanded] = useState(false);
  const isRemovable = result.source_type === "removable_disk";
  const matchSignal = getMatchSignal(result.debug);

  return (
    <div className="p-4 hover:bg-gray-50 transition-colors">
      <div className="flex gap-4">
        <div className="flex-shrink-0 relative">
          <SceneThumbnail
            videoId={result.video_id}
            sceneId={result.scene_id}
            agentAvailable={agentAvailable}
            className="w-32 h-20 rounded-lg"
          />
          <span className="absolute -top-2 -left-2 bg-primary-600 text-white text-xs font-bold w-6 h-6 rounded-full flex items-center justify-center">
            {rank}
          </span>
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2 mb-1">
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-sm font-medium text-gray-900 truncate">
                {result.video_title || result.video_id}
              </span>
              <Breadcrumb libraryName={result.library_name} sourceType={result.source_type} />
              <span className="px-2 py-0.5 rounded-full text-xs font-medium bg-gray-100 text-gray-600">
                {result.speech_segment_count} segment{result.speech_segment_count !== 1 ? "s" : ""}
              </span>
              <span className={cn("px-2 py-0.5 rounded-full text-xs font-medium", matchSignal.color)}>
                {matchSignal.label}
              </span>
            </div>
            <span className="text-xs text-gray-500 whitespace-nowrap">
              {formatDuration(result.start_ms, result.end_ms)}
            </span>
          </div>

          <p className="text-sm text-gray-700 line-clamp-2 mb-2">
            {result.snippet}
          </p>

          {result.ocr_snippet && result.ocr_snippet.trim() && (
            <p className="text-sm text-gray-500 mt-0.5 mb-2 line-clamp-1">
              📺 {result.ocr_snippet}
            </p>
          )}

          {result.scene_caption && result.scene_caption.trim() && (
            <p className="text-sm text-gray-500 mt-0.5 mb-2 line-clamp-1">
              <span className="text-gray-400">AI 캡션</span> {result.scene_caption}
            </p>
          )}

          <div className="flex items-center gap-2 mb-2">
            <span className="text-xs text-gray-500">Quality:</span>
            <div className="flex-1 max-w-[120px] h-1.5 bg-gray-200 rounded-full overflow-hidden">
              <div
                className={cn("h-full rounded-full", getQualityColor(result.debug.quality_factor))}
                style={{ width: `${Math.round(result.debug.quality_factor * 100)}%` }}
              />
            </div>
            <span
              className="text-xs text-gray-400"
              title={`Quality factor: ${result.debug.quality_factor.toFixed(2)}, ${result.speech_segment_count} speech segments`}
            >
              {result.debug.quality_factor.toFixed(2)}
            </span>
          </div>

          <div className="flex items-center gap-3">
            <div className="flex items-center">
              <button
                className={cn(
                  "text-sm flex items-center gap-1 px-2 py-1 rounded-l-md border",
                  agentAvailable
                    ? "text-primary-600 hover:bg-primary-50 border-primary-200 cursor-pointer"
                    : "text-gray-400 border-gray-200 cursor-not-allowed"
                )}
                disabled={!agentAvailable}
                onClick={() => {
                  if (agentAvailable) {
                    window.open(playbackUrl(result.video_id, result.source_type, result.start_ms), "_blank");
                  }
                }}
                title={agentAvailable ? "Play from scene start" : "Playback requires the Heimdex agent"}
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
              <button
                className={cn(
                  "text-xs px-2 py-1 border border-l-0",
                  agentAvailable
                    ? "text-primary-600 hover:bg-primary-50 border-primary-200 cursor-pointer"
                    : "text-gray-400 border-gray-200 cursor-not-allowed"
                )}
                disabled={!agentAvailable}
                onClick={() => {
                  if (agentAvailable) {
                    window.open(
                      playbackUrl(result.video_id, result.source_type, Math.max(0, result.start_ms - 5000)),
                      "_blank"
                    );
                  }
                }}
                title={agentAvailable ? "Play with 5s context before scene" : "Playback requires the Heimdex agent"}
              >
                -5s
              </button>
              <button
                className={cn(
                  "text-xs px-2 py-1 rounded-r-md border border-l-0",
                  agentAvailable
                    ? "text-primary-600 hover:bg-primary-50 border-primary-200 cursor-pointer"
                    : "text-gray-400 border-gray-200 cursor-not-allowed"
                )}
                disabled={!agentAvailable}
                onClick={() => {
                  if (agentAvailable) {
                    window.open(
                      playbackUrl(result.video_id, result.source_type, result.start_ms + 5000),
                      "_blank"
                    );
                  }
                }}
                title={agentAvailable ? "Play from 5s after scene start" : "Playback requires the Heimdex agent"}
              >
                +5s
              </button>
            </div>

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

// ============================================================================
// ResultCard — existing segment result card (unchanged)
// ============================================================================

interface ResultCardProps {
  result: SegmentResult;
  rank: number;
  showDebug: boolean;
  agentAvailable: boolean;
}

function ResultCard({ result, rank, showDebug, agentAvailable }: ResultCardProps) {
  const [expanded, setExpanded] = useState(false);
  const isRemovable = result.source_type === "removable_disk";

  return (
    <div className="card p-4 hover:shadow-md transition-shadow">
      <div className="flex gap-4">
        <div className="flex-shrink-0 relative">
          <SceneThumbnail
            videoId={result.video_id}
            agentAvailable={agentAvailable}
            className="w-32 h-20 rounded-lg"
          />
          <span className="absolute -top-2 -left-2 bg-primary-600 text-white text-xs font-bold w-6 h-6 rounded-full flex items-center justify-center">
            {rank}
          </span>
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-start justify-between gap-2 mb-1">
            <div className="flex items-center gap-2">
              <span className="text-sm font-medium text-gray-900 truncate">
                {result.video_title || result.video_id}
              </span>
              <Breadcrumb libraryName={result.library_name} sourceType={result.source_type} />
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
              className={cn(
                "text-sm flex items-center gap-1 px-2 py-1 rounded-md border",
                agentAvailable
                  ? "text-primary-600 hover:bg-primary-50 border-primary-200 cursor-pointer"
                  : "text-gray-400 border-gray-200 cursor-not-allowed"
              )}
              disabled={!agentAvailable}
              onClick={() => {
                if (agentAvailable) {
                  window.open(playbackUrl(result.video_id, result.source_type, result.start_ms), "_blank");
                }
              }}
              title={agentAvailable ? "Play from segment start" : "Playback requires the Heimdex agent"}
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
              {agentAvailable ? "Play" : "Play (Not available)"}
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

// ============================================================================
// DebugPanel — shared by both card types
// ============================================================================

function DebugPanel({ debug }: { debug: DebugInfo }) {
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
        {debug.ocr_contribution > 0 && (
          <>
            <div>
              <span className="text-gray-500">OCR Contribution:</span>{" "}
              <span className="text-orange-600">
                {debug.ocr_contribution.toFixed(4)}
              </span>
            </div>
            <div />
          </>
        )}
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
