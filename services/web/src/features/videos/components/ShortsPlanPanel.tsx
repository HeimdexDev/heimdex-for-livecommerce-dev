"use client";

import { useEffect, useMemo, useState } from "react";
import { CandidateCard } from "./CandidateCard";
import { ExportModal } from "@/features/basket/ExportModal";
import type { BasketItem } from "@/features/basket/useSceneBasket";
import { useShortsPlan } from "../hooks/useShortsPlan";

interface ShortsPlanPanelProps {
  videoId: string;
  videoTitle: string | null;
  agentAvailable: boolean;
}

export function ShortsPlanPanel({
  videoId,
  videoTitle,
  agentAvailable,
}: ShortsPlanPanelProps) {
  const {
    candidates,
    isGenerating,
    planError,
    totalScenes,
    eligibleScenes,
    selectedIds,
    generatePlan,
    toggleCandidate,
    selectAll,
    deselectAll,
    reset,
  } = useShortsPlan();
  const [isExportDialogOpen, setIsExportDialogOpen] = useState(false);

  useEffect(() => {
    reset();
    setIsExportDialogOpen(false);
  }, [videoId, reset]);

  const selectedCount = selectedIds.size;
  const hasResults = candidates.length > 0;
  const selectedCandidates = useMemo(
    () => candidates.filter((candidate) => selectedIds.has(candidate.candidate_id)),
    [candidates, selectedIds],
  );

  // Map selected candidates to BasketItem[] for the ExportModal
  const exportItems: BasketItem[] = useMemo(
    () =>
      selectedCandidates.map((c) => ({
        scene_id: c.scene_ids[0] ?? c.candidate_id,
        video_id: c.video_id,
        video_title: c.title_suggestion || videoTitle || videoId,
        start_ms: c.start_ms,
        end_ms: c.end_ms,
        label: c.title_suggestion || undefined,
        keyword_tags: c.tags,
        transcript_raw: c.transcript_snippet || undefined,
      })),
    [selectedCandidates, videoTitle, videoId],
  );

  return (
    <div className="border-t border-gray-100 px-6 py-4">
      <h3 className="text-sm font-semibold text-gray-900 mb-3">Shorts Plan</h3>

      {!hasResults && !isGenerating && !planError && (
        <button
          type="button"
          className="btn-primary w-full disabled:opacity-50 disabled:cursor-not-allowed"
          onClick={() => generatePlan(videoId)}
        >
          Generate Shorts Plan
        </button>
      )}

      {!hasResults && isGenerating && (
        <button
          type="button"
          className="btn-primary w-full disabled:opacity-50 disabled:cursor-not-allowed"
          disabled
        >
          Generating...
        </button>
      )}

      {!hasResults && planError && (
        <div className="space-y-3">
          <div className="p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">
            {planError}
          </div>
          <button
            type="button"
            className="btn-primary w-full"
            onClick={() => generatePlan(videoId)}
          >
            Try Again
          </button>
        </div>
      )}

      {hasResults && (
        <>
          <div className="flex items-center justify-between mb-3">
            <p className="text-xs text-gray-500">
              {candidates.length} candidates from {eligibleScenes} eligible scenes
              {totalScenes > 0 ? ` (${totalScenes} total)` : ""}
            </p>
            <button
              type="button"
              className="text-xs font-medium text-primary-600 hover:text-primary-700"
              onClick={selectedCount === candidates.length ? deselectAll : selectAll}
            >
              {selectedCount === candidates.length ? "Deselect All" : "Select All"}
            </button>
          </div>

          <div className="space-y-2">
            {candidates.map((candidate, index) => (
              <CandidateCard
                key={candidate.candidate_id}
                candidate={candidate}
                rank={index + 1}
                isSelected={selectedIds.has(candidate.candidate_id)}
                onToggle={() => toggleCandidate(candidate.candidate_id)}
                agentAvailable={agentAvailable}
                videoId={videoId}
              />
            ))}
          </div>

          <div className="sticky bottom-0 mt-3 pt-3 border-t border-gray-100 bg-white flex items-center justify-between gap-3">
            <span className="text-xs text-gray-600">{selectedCount} selected</span>
            <div className="flex items-center gap-2">
              <button
                type="button"
                className="btn-primary text-sm px-3 py-1.5 disabled:opacity-50 disabled:cursor-not-allowed"
                disabled={selectedCount === 0}
                onClick={() => setIsExportDialogOpen(true)}
              >
                Export to Premiere
              </button>
            </div>
          </div>
        </>
      )}

      <ExportModal
        isOpen={isExportDialogOpen}
        onClose={() => setIsExportDialogOpen(false)}
        overrideItems={exportItems}
      />
    </div>
  );
}
