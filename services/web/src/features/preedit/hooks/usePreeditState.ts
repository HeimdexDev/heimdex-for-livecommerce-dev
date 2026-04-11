import { useReducer, useCallback } from "react";
import { preeditReducer, createProject } from "../lib/reducer";
import type { PreeditProject, PreeditScene } from "../lib/types";

export function usePreeditState(initial?: PreeditProject) {
  const [project, dispatch] = useReducer(
    preeditReducer,
    initial ?? createProject(),
  );

  const initProject = useCallback(
    (p: PreeditProject) => dispatch({ type: "INIT_PROJECT", project: p }),
    [],
  );

  const setTitle = useCallback(
    (title: string) => dispatch({ type: "SET_TITLE", title }),
    [],
  );

  const addRow = useCallback(
    (afterIndex?: number) => dispatch({ type: "ADD_ROW", afterIndex }),
    [],
  );

  const removeRow = useCallback(
    (rowId: string) => dispatch({ type: "REMOVE_ROW", rowId }),
    [],
  );

  const duplicateRow = useCallback(
    (rowId: string) => dispatch({ type: "DUPLICATE_ROW", rowId }),
    [],
  );

  const reorderRows = useCallback(
    (fromIndex: number, toIndex: number) =>
      dispatch({ type: "REORDER_ROWS", fromIndex, toIndex }),
    [],
  );

  const setRowLabel = useCallback(
    (rowId: string, label: string) =>
      dispatch({ type: "SET_ROW_LABEL", rowId, label }),
    [],
  );

  const setRowQuery = useCallback(
    (rowId: string, query: string) =>
      dispatch({ type: "SET_ROW_QUERY", rowId, query }),
    [],
  );

  const selectScene = useCallback(
    (rowId: string, scene: PreeditScene) =>
      dispatch({ type: "SELECT_SCENE", rowId, scene }),
    [],
  );

  const clearScene = useCallback(
    (rowId: string) => dispatch({ type: "CLEAR_SCENE", rowId }),
    [],
  );

  return {
    project,
    initProject,
    setTitle,
    addRow,
    removeRow,
    duplicateRow,
    reorderRows,
    setRowLabel,
    setRowQuery,
    selectScene,
    clearScene,
  };
}
