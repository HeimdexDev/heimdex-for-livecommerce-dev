import type { PreeditProject } from "./types";

const STORAGE_KEY = "heimdex-preedit-projects";

function readAll(): PreeditProject[] {
  if (typeof window === "undefined") return [];
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeAll(projects: PreeditProject[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(projects));
  } catch {
    /* localStorage unavailable */
  }
}

export function saveProject(project: PreeditProject): void {
  const all = readAll();
  const idx = all.findIndex((p) => p.id === project.id);
  if (idx >= 0) {
    all[idx] = project;
  } else {
    all.unshift(project);
  }
  writeAll(all);
}

export function loadProject(id: string): PreeditProject | null {
  const all = readAll();
  return all.find((p) => p.id === id) ?? null;
}

export function listProjects(): PreeditProject[] {
  return readAll().sort(
    (a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime(),
  );
}

export function deleteProject(id: string): void {
  const all = readAll().filter((p) => p.id !== id);
  writeAll(all);
}
