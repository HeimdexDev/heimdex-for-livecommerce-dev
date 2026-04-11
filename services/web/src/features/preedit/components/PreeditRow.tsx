import { useSortable } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { cn } from "@/lib/utils";
import type { PreeditRow as PreeditRowType } from "../lib/types";
import type { PreeditActions } from "./PreeditLayout";
import { RowSearchBar } from "./RowSearchBar";
import { SceneCandidateCard } from "./SceneCandidateCard";
import { SelectedSceneSlot } from "./SelectedSceneSlot";
import { useRowSearch } from "../hooks/useRowSearch";
import { useCallback } from "react";
import type { SceneResult } from "@/lib/types";

type TokenGetter = () => Promise<string | null>;

interface PreeditRowProps {
  row: PreeditRowType;
  index: number;
  actions: PreeditActions;
  getToken: TokenGetter;
}

function formatMs(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

export function PreeditRow({ row, index, actions, getToken }: PreeditRowProps) {
  const { attributes, listeners, setNodeRef, transform, isDragging } =
    useSortable({ id: row.id });

  const style = {
    transform: CSS.Translate.toString(transform),
  };

  const rowSearch = useRowSearch(getToken);

  const handleSearch = useCallback(
    (query: string) => {
      actions.setRowQuery(row.id, query);
      rowSearch.search(query);
    },
    [actions, row.id, rowSearch],
  );

  const handleSelect = useCallback(
    (scene: SceneResult) => {
      actions.selectScene(row.id, {
        sceneId: scene.scene_id,
        videoId: scene.video_id,
        sourceType: scene.source_type,
        videoTitle: scene.video_title,
        startMs: scene.start_ms,
        endMs: scene.end_ms,
        snippet: scene.snippet || scene.scene_caption || "",
        keyframeTimestampMs: scene.keyframe_timestamp_ms,
      });
      rowSearch.clear();
    },
    [actions, row.id, rowSearch],
  );

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "overflow-hidden rounded-lg border border-gray-200 bg-white p-4 transition-shadow",
        isDragging && "z-10 shadow-lg",
      )}
    >
      {/* Row header */}
      <div className="mb-3 flex items-center gap-2">
        <button
          type="button"
          className="cursor-grab touch-none rounded p-1 text-gray-400 hover:text-gray-600"
          {...attributes}
          {...listeners}
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M3.75 6.75h16.5M3.75 12h16.5m-16.5 5.25h16.5" />
          </svg>
        </button>

        <span className="text-sm font-medium text-gray-500">{index + 1}.</span>

        <input
          type="text"
          value={row.label}
          onChange={(e) => actions.setRowLabel(row.id, e.target.value)}
          placeholder="라벨 (예: Hook, 제품 클로즈업)"
          className="flex-1 border-none bg-transparent text-sm text-gray-700 outline-none placeholder:text-gray-400"
        />

        <button
          type="button"
          onClick={() => actions.duplicateRow(row.id)}
          className="rounded p-1 text-gray-400 transition-colors hover:text-gray-600"
          title="행 복제"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 01-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H6.75a9.06 9.06 0 011.5.124m7.5 10.376h3.375c.621 0 1.125-.504 1.125-1.125V11.25c0-4.46-3.243-8.161-7.5-8.876a9.06 9.06 0 00-1.5-.124H9.375c-.621 0-1.125.504-1.125 1.125v3.5m7.5 10.375H9.375a1.125 1.125 0 01-1.125-1.125v-9.25m12 6.625v-1.875a3.375 3.375 0 00-3.375-3.375h-1.5a1.125 1.125 0 01-1.125-1.125v-1.5a3.375 3.375 0 00-3.375-3.375H9.75" />
          </svg>
        </button>

        <button
          type="button"
          onClick={() => actions.removeRow(row.id)}
          className="rounded p-1 text-gray-400 transition-colors hover:text-red-500"
          title="행 삭제"
        >
          <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
          </svg>
        </button>
      </div>

      {/* Search */}
      <RowSearchBar
        query={row.query}
        onSearch={handleSearch}
        isLoading={rowSearch.isLoading}
      />

      {/* Search error */}
      {rowSearch.error && (
        <p className="mt-2 text-xs text-red-500">{rowSearch.error}</p>
      )}

      {/* Search results */}
      {rowSearch.results.length > 0 && (
        <div className="mt-3 flex gap-3 overflow-x-auto pb-2">
          {rowSearch.results.map((scene) => (
            <SceneCandidateCard
              key={scene.scene_id}
              scene={scene}
              onSelect={() => handleSelect(scene)}
            />
          ))}
        </div>
      )}

      {/* Selected scene */}
      <div className="mt-3">
        <SelectedSceneSlot
          scene={row.selectedScene}
          onClear={() => actions.clearScene(row.id)}
          formatMs={formatMs}
        />
      </div>
    </div>
  );
}
