import {
  DndContext,
  closestCenter,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import type { SceneResult } from "@/lib/types";
import type { PreeditRow as PreeditRowType } from "../lib/types";
import type { PreeditActions } from "./PreeditLayout";
import { PreeditRow } from "./PreeditRow";

type TokenGetter = () => Promise<string | null>;

interface RowListProps {
  rows: PreeditRowType[];
  actions: PreeditActions;
  getToken: TokenGetter;
  onPreviewScene: (scene: SceneResult) => void;
}

export function RowList({ rows, actions, getToken, onPreviewScene }: RowListProps) {
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
  );

  function handleDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over || active.id === over.id) return;

    const fromIndex = rows.findIndex((r) => r.id === active.id);
    const toIndex = rows.findIndex((r) => r.id === over.id);
    if (fromIndex >= 0 && toIndex >= 0) {
      actions.reorderRows(fromIndex, toIndex);
    }
  }

  return (
    <div className="flex w-full flex-col gap-4 overflow-hidden">
      <DndContext
        sensors={sensors}
        collisionDetection={closestCenter}
        onDragEnd={handleDragEnd}
      >
        <SortableContext
          items={rows.map((r) => r.id)}
          strategy={verticalListSortingStrategy}
        >
          {rows.map((row, index) => (
            <PreeditRow
              key={row.id}
              row={row}
              index={index}
              actions={actions}
              getToken={getToken}
              onPreviewScene={onPreviewScene}
            />
          ))}
        </SortableContext>
      </DndContext>

      <button
        type="button"
        onClick={() => actions.addRow()}
        className="flex w-full items-center justify-center gap-2 rounded-lg border-2 border-dashed border-gray-300 py-3 text-sm text-gray-500 transition-colors hover:border-indigo-400 hover:text-indigo-600"
      >
        <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 4.5v15m7.5-7.5h-15" />
        </svg>
        행 추가
      </button>
    </div>
  );
}
