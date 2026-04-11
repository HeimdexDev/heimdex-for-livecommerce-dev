import { describe, expect, it, beforeEach } from "vitest";
import {
  saveProject,
  loadProject,
  listProjects,
  deleteProject,
} from "../lib/storage";
import type { PreeditProject } from "../lib/types";

function makeProject(overrides: Partial<PreeditProject> = {}): PreeditProject {
  return {
    id: "proj-1",
    title: "Test Project",
    rows: [],
    createdAt: "2026-01-01T00:00:00.000Z",
    updatedAt: "2026-01-01T00:00:00.000Z",
    ...overrides,
  };
}

describe("preedit storage", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  describe("saveProject", () => {
    it("saves a new project", () => {
      const project = makeProject();
      saveProject(project);
      expect(loadProject("proj-1")).toEqual(project);
    });

    it("updates existing project by id", () => {
      saveProject(makeProject({ title: "v1" }));
      saveProject(makeProject({ title: "v2" }));
      expect(loadProject("proj-1")?.title).toBe("v2");
      expect(listProjects()).toHaveLength(1);
    });
  });

  describe("loadProject", () => {
    it("returns null for unknown id", () => {
      expect(loadProject("nonexistent")).toBeNull();
    });

    it("returns null when storage is empty", () => {
      expect(loadProject("proj-1")).toBeNull();
    });
  });

  describe("listProjects", () => {
    it("returns empty array when no projects", () => {
      expect(listProjects()).toEqual([]);
    });

    it("returns projects sorted by updatedAt descending", () => {
      saveProject(
        makeProject({ id: "a", updatedAt: "2026-01-01T00:00:00.000Z" }),
      );
      saveProject(
        makeProject({ id: "b", updatedAt: "2026-01-03T00:00:00.000Z" }),
      );
      saveProject(
        makeProject({ id: "c", updatedAt: "2026-01-02T00:00:00.000Z" }),
      );
      const list = listProjects();
      expect(list.map((p) => p.id)).toEqual(["b", "c", "a"]);
    });
  });

  describe("deleteProject", () => {
    it("removes project by id", () => {
      saveProject(makeProject({ id: "a" }));
      saveProject(makeProject({ id: "b" }));
      deleteProject("a");
      expect(loadProject("a")).toBeNull();
      expect(loadProject("b")).not.toBeNull();
    });

    it("is no-op for unknown id", () => {
      saveProject(makeProject());
      deleteProject("nonexistent");
      expect(listProjects()).toHaveLength(1);
    });
  });

  describe("corruption recovery", () => {
    it("returns empty array when storage has invalid JSON", () => {
      localStorage.setItem("heimdex-preedit-projects", "not-json");
      expect(listProjects()).toEqual([]);
    });

    it("returns empty array when storage has non-array JSON", () => {
      localStorage.setItem(
        "heimdex-preedit-projects",
        JSON.stringify({ foo: "bar" }),
      );
      expect(listProjects()).toEqual([]);
    });
  });
});
