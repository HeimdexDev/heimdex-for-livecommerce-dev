"use client";

import { useEffect, useMemo, useState } from "react";
import { CandidateCard } from "./CandidateCard";
import { ExportDialog } from "./ExportDialog";
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
    isExporting,
    exportError,
    exportResult,
    generatePlan,
    toggleCandidate,
    selectAll,
    deselectAll,
    exportSelectedToPremiere,
    clearExportResult,
    reset,
  } = useShortsPlan();
  const [isExportDialogOpen, setIsExportDialogOpen] = useState(false);

  useEffect(() => {
    reset();
    setIsExportDialogOpen(false);
  }, [videoId, reset]);

  const selectedCount = selectedIds.size;
  const hasResults = candidates.length > 0;
  const defaultProjectName = useMemo(() => {
    const baseName = (videoTitle || videoId).trim();
    return `${baseName} Shorts`;
  }, [videoTitle, videoId]);

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
                disabled={selectedCount === 0 || !agentAvailable || isExporting}
                onClick={() => setIsExportDialogOpen(true)}
              >
                {isExporting ? "Exporting..." : "Export to Premiere"}
              </button>
              {!agentAvailable && <span className="text-xs text-gray-500">(Agent offline)</span>}
            </div>
          </div>

          {exportResult && (
            <div className="mt-3 p-3 bg-green-50 border border-green-200 rounded-lg text-green-700 text-sm flex items-start justify-between gap-2">
              <p className="min-w-0 break-words">Exported to {exportResult.output_path}</p>
              <button
                type="button"
                className="text-green-700 hover:text-green-800 font-medium"
                onClick={clearExportResult}
              >
                Dismiss
              </button>
            </div>
          )}

          {exportError && (
            <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm flex items-start justify-between gap-2">
              <p className="min-w-0 break-words">{exportError}</p>
              <button
                type="button"
                className="text-red-700 hover:text-red-800 font-medium"
                onClick={clearExportResult}
              >
                Dismiss
              </button>
            </div>
          )}
        </>
      )}

      <ExportDialog
        isOpen={isExportDialogOpen}
        onClose={() => {
          if (!isExporting) {
            setIsExportDialogOpen(false);
          }
        }}
        onExport={(config) => {
          void exportSelectedToPremiere(config);
          setIsExportDialogOpen(false);
        }}
        selectedCount={selectedCount}
        isExporting={isExporting}
        defaultProjectName={defaultProjectName}
        agentAvailable={agentAvailable}
      />
    </div>
  );
}
