import { useEffect, useRef } from "react";
import { saveProject } from "../lib/storage";
import type { PreeditProject } from "../lib/types";

const DEBOUNCE_MS = 1000;

export function useAutoSave(project: PreeditProject) {
  const isFirstRender = useRef(true);

  useEffect(() => {
    // Skip saving on first render to avoid overwriting with initial state
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }

    const timer = setTimeout(() => {
      saveProject(project);
    }, DEBOUNCE_MS);

    return () => clearTimeout(timer);
  }, [project]);
}
