import type { PreeditProject, PreeditAction, PreeditRow } from "./types";

function createRow(): PreeditRow {
  return {
    id: crypto.randomUUID(),
    label: "",
    query: "",
    selectedScene: null,
  };
}

export function createProject(): PreeditProject {
  return {
    id: crypto.randomUUID(),
    title: "",
    rows: [createRow()],
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
}

function updateTimestamp(project: PreeditProject): PreeditProject {
  return { ...project, updatedAt: new Date().toISOString() };
}

export function preeditReducer(
  state: PreeditProject,
  action: PreeditAction,
): PreeditProject {
  switch (action.type) {
    case "INIT_PROJECT":
      return action.project;

    case "SET_TITLE":
      return updateTimestamp({ ...state, title: action.title });

    case "ADD_ROW": {
      const newRow = createRow();
      const rows = [...state.rows];
      const insertAt =
        action.afterIndex != null ? action.afterIndex + 1 : rows.length;
      rows.splice(insertAt, 0, newRow);
      return updateTimestamp({ ...state, rows });
    }

    case "REMOVE_ROW":
      return updateTimestamp({
        ...state,
        rows: state.rows.filter((r) => r.id !== action.rowId),
      });

    case "DUPLICATE_ROW": {
      const idx = state.rows.findIndex((r) => r.id === action.rowId);
      if (idx === -1) return state;
      const original = state.rows[idx];
      const clone: PreeditRow = {
        ...original,
        id: crypto.randomUUID(),
        label: original.label ? `${original.label} (copy)` : "",
      };
      const rows = [...state.rows];
      rows.splice(idx + 1, 0, clone);
      return updateTimestamp({ ...state, rows });
    }

    case "REORDER_ROWS": {
      const { fromIndex, toIndex } = action;
      if (
        fromIndex === toIndex ||
        fromIndex < 0 ||
        toIndex < 0 ||
        fromIndex >= state.rows.length ||
        toIndex >= state.rows.length
      )
        return state;
      const rows = [...state.rows];
      const [moved] = rows.splice(fromIndex, 1);
      rows.splice(toIndex, 0, moved);
      return updateTimestamp({ ...state, rows });
    }

    case "SET_ROW_LABEL":
      return updateTimestamp({
        ...state,
        rows: state.rows.map((r) =>
          r.id === action.rowId ? { ...r, label: action.label } : r,
        ),
      });

    case "SET_ROW_QUERY":
      return updateTimestamp({
        ...state,
        rows: state.rows.map((r) =>
          r.id === action.rowId ? { ...r, query: action.query } : r,
        ),
      });

    case "SELECT_SCENE":
      return updateTimestamp({
        ...state,
        rows: state.rows.map((r) =>
          r.id === action.rowId
            ? { ...r, selectedScene: action.scene }
            : r,
        ),
      });

    case "CLEAR_SCENE":
      return updateTimestamp({
        ...state,
        rows: state.rows.map((r) =>
          r.id === action.rowId ? { ...r, selectedScene: null } : r,
        ),
      });

    case "MARK_CLEAN":
      return state;

    default:
      return state;
  }
}
