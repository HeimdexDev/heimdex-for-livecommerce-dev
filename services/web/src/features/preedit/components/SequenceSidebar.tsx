import type { SceneResult } from "@/lib/types";
import type { RenderJobResponse } from "@/lib/api/shorts-render";
import type { PreeditProject } from "../lib/types";
import { ScenePreviewPlayer, ScenePreviewEmpty } from "./ScenePreviewPlayer";
import { ExportPanel } from "./ExportPanel";
import { SequenceItem } from "./SequenceItem";

type TokenGetter = () => Promise<string | null>;

// Keep this union in sync with usePreeditExport.ts and ExportPanel.tsx.
// `rate_limited` is surfaced distinctly from `failed` for 429 responses.
interface ExportState {
  renderStatus:
    | "idle"
    | "submitting"
    | "queued"
    | "rendering"
    | "completed"
    | "failed"
    | "rate_limited";
  renderJob: RenderJobResponse | null;
  renderError: string | null;
  submitRender: () => Promise<void>;
  exportPremiere: (driveMountPath: string) => Promise<void>;
  premiereError: string | null;
  isExportingPremiere: boolean;
  reset: () => void;
}

interface SequenceSidebarProps {
  project: PreeditProject;
  previewScene: SceneResult | null;
  exportState: ExportState;
  getToken: TokenGetter;
}

function formatDuration(totalMs: number): string {
  const totalSeconds = Math.floor(totalMs / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}분 ${s}초`;
}

export function SequenceSidebar({ project, previewScene, exportState, getToken }: SequenceSidebarProps) {
  const filledRows = project.rows.filter((r) => r.selectedScene !== null);
  const totalDurationMs = filledRows.reduce((sum, row) => {
    const scene = row.selectedScene!;
    return sum + (scene.endMs - scene.startMs);
  }, 0);

  return (
    <div className="flex h-full flex-col p-4">
      {/* Preview player */}
      <div className="mb-4">
        <h2 className="mb-2 text-sm font-semibold text-gray-800">미리보기</h2>
        {previewScene ? (
          <ScenePreviewPlayer key={previewScene.scene_id} scene={previewScene} />
        ) : (
          <ScenePreviewEmpty />
        )}
      </div>

      {/* Sequence section */}
      <div className="flex flex-1 flex-col border-t border-gray-200 pt-4 overflow-hidden">
        <h2 className="text-sm font-semibold text-gray-800">시퀀스</h2>
        <p className="mt-1 text-xs text-gray-500">
          {filledRows.length}/{project.rows.length} 행 선택됨
        </p>

        <div className="mt-4 flex flex-1 flex-col gap-2 overflow-y-auto">
          {project.rows.map((row, index) => (
            <SequenceItem key={row.id} row={row} index={index} />
          ))}

          {project.rows.length === 0 && (
            <p className="py-8 text-center text-xs text-gray-400">
              행을 추가하여 시작하세요
            </p>
          )}
        </div>

        <div className="mt-4 border-t border-gray-200 pt-4">
          <div className="flex items-center justify-between text-sm">
            <span className="text-gray-600">총 길이</span>
            <span className="font-medium text-gray-900">
              {totalDurationMs > 0 ? formatDuration(totalDurationMs) : "—"}
            </span>
          </div>

          <div className="mt-4">
            <ExportPanel
              hasFilledRows={filledRows.length > 0}
              renderStatus={exportState.renderStatus}
              renderJob={exportState.renderJob}
              renderError={exportState.renderError}
              onSubmitRender={exportState.submitRender}
              onExportPremiere={exportState.exportPremiere}
              premiereError={exportState.premiereError}
              isExportingPremiere={exportState.isExportingPremiere}
              onReset={exportState.reset}
              getToken={getToken}
            />
          </div>
        </div>
      </div>
    </div>
  );
}
