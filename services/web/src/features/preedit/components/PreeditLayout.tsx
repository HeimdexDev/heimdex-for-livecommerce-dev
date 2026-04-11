import type { PreeditProject, PreeditScene } from "../lib/types";
import { PreeditHeader } from "./PreeditHeader";
import { RowList } from "./RowList";
import { SequenceSidebar } from "./SequenceSidebar";

export interface PreeditActions {
  setTitle: (title: string) => void;
  addRow: (afterIndex?: number) => void;
  removeRow: (rowId: string) => void;
  duplicateRow: (rowId: string) => void;
  reorderRows: (fromIndex: number, toIndex: number) => void;
  setRowLabel: (rowId: string, label: string) => void;
  setRowQuery: (rowId: string, query: string) => void;
  selectScene: (rowId: string, scene: PreeditScene) => void;
  clearScene: (rowId: string) => void;
}

type TokenGetter = () => Promise<string | null>;

interface PreeditLayoutProps {
  project: PreeditProject;
  actions: PreeditActions;
  getToken: TokenGetter;
}

export function PreeditLayout({
  project,
  actions,
  getToken,
}: PreeditLayoutProps) {
  return (
    <div className="flex h-[calc(100vh-64px)] w-full flex-col overflow-hidden">
      <PreeditHeader
        title={project.title}
        onTitleChange={actions.setTitle}
      />
      <div className="flex flex-1 overflow-hidden">
        <main className="min-w-0 flex-1 overflow-y-auto p-6">
          <RowList
            rows={project.rows}
            actions={actions}
            getToken={getToken}
          />
        </main>
        <aside className="w-[320px] flex-shrink-0 overflow-y-auto border-l border-gray-200 bg-gray-50">
          <SequenceSidebar project={project} />
        </aside>
      </div>
    </div>
  );
}
