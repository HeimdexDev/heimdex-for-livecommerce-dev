import { describe, expect, it, vi, beforeEach } from "vitest";
import { preeditReducer, createProject } from "../lib/reducer";
import type { PreeditProject, PreeditScene, PreeditAction } from "../lib/types";

// Stable UUID for tests
let uuidCounter = 0;
beforeEach(() => {
  uuidCounter = 0;
  vi.spyOn(crypto, "randomUUID").mockImplementation(
    () => `test-uuid-${++uuidCounter}` as `${string}-${string}-${string}-${string}-${string}`,
  );
});

const mockScene: PreeditScene = {
  sceneId: "scene-001",
  videoId: "video-abc",
  sourceType: "gdrive",
  videoTitle: "Test Video",
  startMs: 5000,
  endMs: 15000,
  snippet: "hello world",
  keyframeTimestampMs: 7000,
};

function projectWithRows(count: number): PreeditProject {
  return {
    id: "project-1",
    title: "",
    rows: Array.from({ length: count }, (_, i) => ({
      id: `row-${i}`,
      label: `Label ${i}`,
      query: "",
      selectedScene: null,
    })),
    createdAt: "2026-01-01T00:00:00.000Z",
    updatedAt: "2026-01-01T00:00:00.000Z",
  };
}

describe("preeditReducer", () => {
  describe("INIT_PROJECT", () => {
    it("replaces entire state", () => {
      const initial = createProject();
      const replacement = { ...createProject(), title: "Loaded" };
      const result = preeditReducer(initial, {
        type: "INIT_PROJECT",
        project: replacement,
      });
      expect(result).toBe(replacement);
    });
  });

  describe("SET_TITLE", () => {
    it("updates project title", () => {
      const state = createProject();
      const result = preeditReducer(state, {
        type: "SET_TITLE",
        title: "My Rough Cut",
      });
      expect(result.title).toBe("My Rough Cut");
    });
  });

  describe("ADD_ROW", () => {
    it("appends row at end by default", () => {
      const state = projectWithRows(2);
      const result = preeditReducer(state, { type: "ADD_ROW" });
      expect(result.rows).toHaveLength(3);
      expect(result.rows[2].label).toBe("");
      expect(result.rows[2].selectedScene).toBeNull();
    });

    it("inserts after specified index", () => {
      const state = projectWithRows(3);
      const result = preeditReducer(state, {
        type: "ADD_ROW",
        afterIndex: 0,
      });
      expect(result.rows).toHaveLength(4);
      expect(result.rows[0].id).toBe("row-0");
      expect(result.rows[1].label).toBe(""); // new row
      expect(result.rows[2].id).toBe("row-1");
    });

    it("creates row with empty fields", () => {
      const state = projectWithRows(0);
      const result = preeditReducer(state, { type: "ADD_ROW" });
      const row = result.rows[0];
      expect(row.label).toBe("");
      expect(row.query).toBe("");
      expect(row.selectedScene).toBeNull();
    });
  });

  describe("REMOVE_ROW", () => {
    it("removes row by id", () => {
      const state = projectWithRows(3);
      const result = preeditReducer(state, {
        type: "REMOVE_ROW",
        rowId: "row-1",
      });
      expect(result.rows).toHaveLength(2);
      expect(result.rows.map((r) => r.id)).toEqual(["row-0", "row-2"]);
    });

    it("handles removing last row", () => {
      const state = projectWithRows(1);
      const result = preeditReducer(state, {
        type: "REMOVE_ROW",
        rowId: "row-0",
      });
      expect(result.rows).toHaveLength(0);
    });

    it("is no-op for unknown id", () => {
      const state = projectWithRows(2);
      const result = preeditReducer(state, {
        type: "REMOVE_ROW",
        rowId: "nonexistent",
      });
      expect(result.rows).toHaveLength(2);
    });
  });

  describe("DUPLICATE_ROW", () => {
    it("clones row after original", () => {
      const state = projectWithRows(2);
      state.rows[0].label = "Hook";
      state.rows[0].selectedScene = mockScene;

      const result = preeditReducer(state, {
        type: "DUPLICATE_ROW",
        rowId: "row-0",
      });
      expect(result.rows).toHaveLength(3);
      expect(result.rows[1].label).toBe("Hook (copy)");
      expect(result.rows[1].selectedScene).toEqual(mockScene);
      expect(result.rows[1].id).not.toBe("row-0");
    });

    it("is no-op for unknown id", () => {
      const state = projectWithRows(2);
      const result = preeditReducer(state, {
        type: "DUPLICATE_ROW",
        rowId: "nonexistent",
      });
      expect(result.rows).toHaveLength(2);
    });

    it("appends (copy) only when label exists", () => {
      const state = projectWithRows(1);
      state.rows[0].label = "";
      const result = preeditReducer(state, {
        type: "DUPLICATE_ROW",
        rowId: "row-0",
      });
      expect(result.rows[1].label).toBe("");
    });
  });

  describe("REORDER_ROWS", () => {
    it("moves row forward", () => {
      const state = projectWithRows(3);
      const result = preeditReducer(state, {
        type: "REORDER_ROWS",
        fromIndex: 0,
        toIndex: 2,
      });
      expect(result.rows.map((r) => r.id)).toEqual([
        "row-1",
        "row-2",
        "row-0",
      ]);
    });

    it("moves row backward", () => {
      const state = projectWithRows(3);
      const result = preeditReducer(state, {
        type: "REORDER_ROWS",
        fromIndex: 2,
        toIndex: 0,
      });
      expect(result.rows.map((r) => r.id)).toEqual([
        "row-2",
        "row-0",
        "row-1",
      ]);
    });

    it("is no-op when fromIndex equals toIndex", () => {
      const state = projectWithRows(3);
      const result = preeditReducer(state, {
        type: "REORDER_ROWS",
        fromIndex: 1,
        toIndex: 1,
      });
      expect(result).toBe(state);
    });

    it("is no-op for out-of-bounds indices", () => {
      const state = projectWithRows(2);
      const result = preeditReducer(state, {
        type: "REORDER_ROWS",
        fromIndex: -1,
        toIndex: 0,
      });
      expect(result).toBe(state);
    });
  });

  describe("SET_ROW_LABEL", () => {
    it("updates label on matching row", () => {
      const state = projectWithRows(2);
      const result = preeditReducer(state, {
        type: "SET_ROW_LABEL",
        rowId: "row-0",
        label: "Hook",
      });
      expect(result.rows[0].label).toBe("Hook");
      expect(result.rows[1].label).toBe("Label 1");
    });
  });

  describe("SET_ROW_QUERY", () => {
    it("updates query on matching row", () => {
      const state = projectWithRows(1);
      const result = preeditReducer(state, {
        type: "SET_ROW_QUERY",
        rowId: "row-0",
        query: "host smiling",
      });
      expect(result.rows[0].query).toBe("host smiling");
    });
  });

  describe("SELECT_SCENE", () => {
    it("sets selected scene on row", () => {
      const state = projectWithRows(2);
      const result = preeditReducer(state, {
        type: "SELECT_SCENE",
        rowId: "row-1",
        scene: mockScene,
      });
      expect(result.rows[1].selectedScene).toEqual(mockScene);
      expect(result.rows[0].selectedScene).toBeNull();
    });

    it("replaces existing selected scene", () => {
      const state = projectWithRows(1);
      state.rows[0].selectedScene = mockScene;
      const newScene = { ...mockScene, sceneId: "scene-002" };
      const result = preeditReducer(state, {
        type: "SELECT_SCENE",
        rowId: "row-0",
        scene: newScene,
      });
      expect(result.rows[0].selectedScene?.sceneId).toBe("scene-002");
    });
  });

  describe("CLEAR_SCENE", () => {
    it("clears selected scene on row", () => {
      const state = projectWithRows(1);
      state.rows[0].selectedScene = mockScene;
      const result = preeditReducer(state, {
        type: "CLEAR_SCENE",
        rowId: "row-0",
      });
      expect(result.rows[0].selectedScene).toBeNull();
    });
  });

  describe("MARK_CLEAN", () => {
    it("returns state unchanged", () => {
      const state = createProject();
      const result = preeditReducer(state, { type: "MARK_CLEAN" });
      expect(result).toBe(state);
    });
  });

  describe("timestamp updates", () => {
    it("updates updatedAt on mutations", () => {
      const state = projectWithRows(1);
      // updatedAt is "2026-01-01T00:00:00.000Z" from projectWithRows
      const result = preeditReducer(state, {
        type: "SET_TITLE",
        title: "New",
      });
      expect(result.updatedAt).not.toBe(state.updatedAt);
    });
  });
});

describe("createProject", () => {
  it("creates project with one empty row", () => {
    const project = createProject();
    expect(project.rows).toHaveLength(1);
    expect(project.rows[0].selectedScene).toBeNull();
    expect(project.title).toBe("");
  });
});
