"use client";

import { useState, useCallback, useMemo } from "react";
import { useAuth } from "@/lib/auth";
import { generateShortsPlan } from "@/lib/api/shorts";
import { exportToPremiere } from "@/lib/agent-export";
import { exportEdlCloud } from "@/lib/cloud-export";
import type {
  ExportPremiereResponse,
  ShortsCandidateResponse,
  ShortsPlanRequest,
} from "@/lib/types";
import { ApiError } from "@/lib/types";

export interface UseShortsPlanReturn {
  candidates: ShortsCandidateResponse[];
  isGenerating: boolean;
  planError: string | null;
  totalScenes: number;
  eligibleScenes: number;
  selectedIds: Set<string>;
  isExporting: boolean;
  exportError: string | null;
  exportWarning: string | null;
  exportResult: ExportPremiereResponse | null;
  isCloudExport: boolean;
  generatePlan: (videoId: string, request?: ShortsPlanRequest) => Promise<void>;
  toggleCandidate: (candidateId: string) => void;
  selectAll: () => void;
  deselectAll: () => void;
  exportSelectedToPremiere: (config: {
    projectName: string;
    outputDir: string;
    frameRate: number;
    agentAvailable: boolean;
  }) => Promise<void>;
  clearExportResult: () => void;
  reset: () => void;
}

export function useShortsPlan(): UseShortsPlanReturn {
  const { getAccessToken } = useAuth();

  const [candidates, setCandidates] = useState<ShortsCandidateResponse[]>([]);
  const [isGenerating, setIsGenerating] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);
  const [totalScenes, setTotalScenes] = useState(0);
  const [eligibleScenes, setEligibleScenes] = useState(0);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [isExporting, setIsExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);
  const [exportWarning, setExportWarning] = useState<string | null>(null);
  const [exportResult, setExportResult] = useState<ExportPremiereResponse | null>(null);

  const generatePlan = useCallback(
    async (videoId: string, request?: ShortsPlanRequest) => {
      setIsGenerating(true);
      setPlanError(null);
      setExportError(null);
      setExportWarning(null);
      setExportResult(null);

      try {
        const response = await generateShortsPlan(videoId, request, getAccessToken);
        setCandidates(response.candidates);
        setTotalScenes(response.total_scenes);
        setEligibleScenes(response.eligible_scenes);
        setSelectedIds(new Set(response.candidates.map((candidate) => candidate.candidate_id)));
      } catch (err) {
        const message = err instanceof ApiError ? err.detail : "Failed to generate shorts plan";
        setPlanError(message);
        setCandidates([]);
        setSelectedIds(new Set());
        setTotalScenes(0);
        setEligibleScenes(0);
      } finally {
        setIsGenerating(false);
      }
    },
    [getAccessToken],
  );

  const toggleCandidate = useCallback((candidateId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(candidateId)) {
        next.delete(candidateId);
      } else {
        next.add(candidateId);
      }
      return next;
    });
  }, []);

  const selectAll = useCallback(() => {
    setSelectedIds(new Set(candidates.map((candidate) => candidate.candidate_id)));
  }, [candidates]);

  const deselectAll = useCallback(() => {
    setSelectedIds(new Set());
  }, []);

  const isCloudExport = useMemo(
    () => candidates.length > 0 && candidates.every((c) => c.video_id.startsWith("gd_")),
    [candidates],
  );

  const exportSelectedToPremiere = useCallback(
    async (config: {
      projectName: string;
      outputDir: string;
      frameRate: number;
      agentAvailable: boolean;
    }) => {
      const selectedCandidates = candidates.filter((candidate) =>
        selectedIds.has(candidate.candidate_id),
      );
      if (selectedCandidates.length === 0) {
        setExportError("Select at least one candidate to export");
        return;
      }

      setIsExporting(true);
      setExportError(null);
      setExportWarning(null);
      setExportResult(null);

      try {
        const allClips = selectedCandidates.map((candidate, index) => ({
          video_id: candidate.video_id,
          scene_id: candidate.scene_ids[0] || candidate.candidate_id,
          clip_name: candidate.title_suggestion || `Clip ${index + 1}`,
          start_ms: candidate.start_ms,
          end_ms: candidate.end_ms,
        }));

        const cloudCandidates = selectedCandidates.filter((c) => c.video_id.startsWith("gd_"));
        const localCandidates = selectedCandidates.filter((c) => !c.video_id.startsWith("gd_"));
        const cloudClips = allClips.filter((clip) => clip.video_id.startsWith("gd_"));
        const localClips = allClips.filter((clip) => !clip.video_id.startsWith("gd_"));

        const allCloud = cloudCandidates.length === selectedCandidates.length;
        const allLocal = localCandidates.length === selectedCandidates.length;

        if (allCloud) {
          const result = await exportEdlCloud(
            {
              project_name: config.projectName,
              frame_rate: config.frameRate,
              clips: cloudClips,
            },
            getAccessToken,
          );
          setExportResult({
            status: "ok",
            format: "edl",
            output_path: result.filename,
            clip_count: result.clip_count,
            unresolved_clips: result.unresolved_clips,
          });
        } else if (allLocal) {
          const result = await exportToPremiere({
            project_name: config.projectName,
            format: "edl",
            frame_rate: config.frameRate,
            output_dir: config.outputDir,
            clips: localClips,
          });
          setExportResult(result);
        } else {
          const cloudResult = await exportEdlCloud(
            {
              project_name: config.projectName,
              frame_rate: config.frameRate,
              clips: cloudClips,
            },
            getAccessToken,
          );

          if (config.agentAvailable) {
            const localResult = await exportToPremiere({
              project_name: config.projectName,
              format: "edl",
              frame_rate: config.frameRate,
              output_dir: config.outputDir,
              clips: localClips,
            });

            setExportResult({
              status: "ok",
              format: "edl",
              output_path: localResult.output_path,
              clip_count: cloudResult.clip_count + localResult.clip_count,
              unresolved_clips: [...cloudResult.unresolved_clips, ...localResult.unresolved_clips],
            });
          } else {
            const skippedLocal = localCandidates
              .map((candidate, index) => candidate.title_suggestion || `Local Clip ${index + 1}`)
              .join(", ");

            setExportWarning(`Agent offline. Skipped local clips: ${skippedLocal}`);
            setExportResult({
              status: "ok",
              format: "edl",
              output_path: cloudResult.filename,
              clip_count: cloudResult.clip_count,
              unresolved_clips: cloudResult.unresolved_clips,
            });
          }
        }
      } catch (err) {
        const message = err instanceof Error ? err.message : "Failed to export to Premiere";
        setExportError(message);
      } finally {
        setIsExporting(false);
      }
    },
    [candidates, selectedIds, getAccessToken],
  );

  const clearExportResult = useCallback(() => {
    setExportResult(null);
    setExportError(null);
    setExportWarning(null);
  }, []);

  const reset = useCallback(() => {
    setCandidates([]);
    setIsGenerating(false);
    setPlanError(null);
    setTotalScenes(0);
    setEligibleScenes(0);
    setSelectedIds(new Set());
    setIsExporting(false);
    setExportError(null);
    setExportWarning(null);
    setExportResult(null);
  }, []);

  return {
    candidates,
    isGenerating,
    planError,
    totalScenes,
    eligibleScenes,
    selectedIds,
    isExporting,
    exportError,
    exportWarning,
    exportResult,
    isCloudExport,
    generatePlan,
    toggleCandidate,
    selectAll,
    deselectAll,
    exportSelectedToPremiere,
    clearExportResult,
    reset,
  };
}
