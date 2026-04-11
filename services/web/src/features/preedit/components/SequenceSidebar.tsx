import type { SceneResult } from "@/lib/types";
import type { PreeditProject } from "../lib/types";
import { ScenePreviewPlayer, ScenePreviewEmpty } from "./ScenePreviewPlayer";
import { SequenceItem } from "./SequenceItem";

interface SequenceSidebarProps {
  project: PreeditProject;
  previewScene: SceneResult | null;
}

function formatDuration(totalMs: number): string {
  const totalSeconds = Math.floor(totalMs / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}분 ${s}초`;
}

export function SequenceSidebar({ project, previewScene }: SequenceSidebarProps) {
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

          <div className="mt-4 rounded-lg border border-gray-200 bg-white p-3 text-center text-xs text-gray-400">
            내보내기 기능 준비 중
          </div>
        </div>
      </div>
    </div>
  );
}
