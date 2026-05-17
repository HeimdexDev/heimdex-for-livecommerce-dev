export interface PreeditScene {
  sceneId: string;
  videoId: string;
  sourceType: string;
  videoTitle: string | null;
  startMs: number;
  endMs: number;
  snippet: string;
  keyframeTimestampMs: number;
}

export interface PreeditRow {
  id: string;
  label: string;
  query: string;
  selectedScene: PreeditScene | null;
}

export interface PreeditProject {
  id: string;
  title: string;
  rows: PreeditRow[];
  createdAt: string;
  updatedAt: string;
}

export type PreeditAction =
  | { type: "INIT_PROJECT"; project: PreeditProject }
  | { type: "SET_TITLE"; title: string }
  | { type: "ADD_ROW"; afterIndex?: number }
  | { type: "REMOVE_ROW"; rowId: string }
  | { type: "DUPLICATE_ROW"; rowId: string }
  | { type: "REORDER_ROWS"; fromIndex: number; toIndex: number }
  | { type: "SET_ROW_LABEL"; rowId: string; label: string }
  | { type: "SET_ROW_QUERY"; rowId: string; query: string }
  | { type: "SELECT_SCENE"; rowId: string; scene: PreeditScene }
  | { type: "CLEAR_SCENE"; rowId: string }
  | { type: "MARK_CLEAN" };
