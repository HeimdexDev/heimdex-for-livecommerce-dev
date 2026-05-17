"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@/lib/auth";
import { usePreeditState } from "../hooks/usePreeditState";
import { useAutoSave } from "../hooks/useAutoSave";
import { loadProject, listProjects } from "../lib/storage";
import { PreeditLayout } from "./PreeditLayout";

export function PreeditPage() {
  const { getAccessToken } = useAuth();
  const [initialized, setInitialized] = useState(false);
  const state = usePreeditState();

  useEffect(() => {
    // Load most recent project from localStorage on mount
    const projects = listProjects();
    if (projects.length > 0) {
      const latest = loadProject(projects[0].id);
      if (latest) {
        state.initProject(latest);
      }
    }
    setInitialized(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useAutoSave(state.project);

  if (!initialized) {
    return (
      <div className="flex min-h-[400px] items-center justify-center">
        <div className="h-10 w-10 animate-spin rounded-full border-b-2 border-indigo-500" />
      </div>
    );
  }

  return (
    <PreeditLayout
      project={state.project}
      actions={state}
      getToken={getAccessToken}
    />
  );
}
