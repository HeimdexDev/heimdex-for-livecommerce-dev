import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { usePeople } from "./usePeople";
import * as peopleApi from "@/lib/api/people";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    getAccessToken: vi.fn().mockResolvedValue("test-token"),
  }),
}));

vi.mock("@/lib/api/people", () => ({
  getPeople: vi.fn().mockResolvedValue({
    people: [
      {
        person_cluster_id: "person-1",
        label: "Person 1",
        face_count: 5,
        last_seen_scene_time: "2026-03-15T10:00:00Z",
        representative_video_id: "video-1",
        representative_scene_id: "scene-1",
        is_excluded: false,
      },
      {
        person_cluster_id: "person-2",
        label: "Person 2",
        face_count: 3,
        last_seen_scene_time: "2026-03-15T09:00:00Z",
        representative_video_id: "video-2",
        representative_scene_id: "scene-2",
        is_excluded: false,
      },
      {
        person_cluster_id: "person-3",
        label: "Person 3",
        face_count: 2,
        last_seen_scene_time: "2026-03-15T08:00:00Z",
        representative_video_id: "video-3",
        representative_scene_id: "scene-3",
        is_excluded: false,
      },
    ],
    total: 3,
  }),
  getExcludePreferences: vi.fn().mockResolvedValue({
    excluded_person_cluster_ids: [],
  }),
  renamePerson: vi.fn(),
  deletePerson: vi.fn(),
  mergePeople: vi.fn(),
  saveExcludePreferences: vi.fn(),
  bulkDeletePeople: vi.fn().mockResolvedValue({
    deleted_ids: [],
    failed_ids: [],
    total_deleted: 0,
  }),
}));

describe("usePeople", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  describe("selectAll", () => {
    it("should set selectedIds to all people IDs", async () => {
      const { result } = renderHook(() => usePeople());

      await waitFor(() => {
        expect(result.current.people.length).toBe(3);
      });

      act(() => {
        result.current.selectAll();
      });

      expect(result.current.selectedIds.size).toBe(3);
      expect(result.current.selectedIds.has("person-1")).toBe(true);
      expect(result.current.selectedIds.has("person-2")).toBe(true);
      expect(result.current.selectedIds.has("person-3")).toBe(true);
    });

    it("should handle empty people list", async () => {
      vi.mocked(peopleApi.getPeople).mockResolvedValueOnce({
        people: [],
        total: 0,
      });

      const { result } = renderHook(() => usePeople());

      await waitFor(() => {
        expect(result.current.people.length).toBe(0);
      });

      act(() => {
        result.current.selectAll();
      });

      expect(result.current.selectedIds.size).toBe(0);
    });
  });

  describe("clearSelection", () => {
    it("should clear all selected IDs", async () => {
      const { result } = renderHook(() => usePeople());

      await waitFor(() => {
        expect(result.current.people.length).toBe(3);
      });

      // First select all
      act(() => {
        result.current.selectAll();
      });

      expect(result.current.selectedIds.size).toBe(3);

      // Then clear
      act(() => {
        result.current.clearSelection();
      });

      expect(result.current.selectedIds.size).toBe(0);
    });

    it("should handle clearing empty selection", async () => {
      const { result } = renderHook(() => usePeople());

      await waitFor(() => {
        expect(result.current.people.length).toBe(3);
      });

      act(() => {
        result.current.clearSelection();
      });

      expect(result.current.selectedIds.size).toBe(0);
    });
  });

  describe("bulkDelete", () => {
    it("should delete multiple people and update state", async () => {
      const { result } = renderHook(() => usePeople());

      await waitFor(() => {
        expect(result.current.people.length).toBe(3);
      });

      const idsToDelete = ["person-1", "person-2"];

      await act(async () => {
        await result.current.bulkDelete(idsToDelete);
      });

      expect(vi.mocked(peopleApi.bulkDeletePeople)).toHaveBeenCalledWith(
        { person_cluster_ids: idsToDelete },
        expect.any(Function),
      );

      expect(result.current.people.length).toBe(1);
      expect(result.current.people[0].person_cluster_id).toBe("person-3");
    });

    it("should remove deleted IDs from selectedIds", async () => {
      const { result } = renderHook(() => usePeople());

      await waitFor(() => {
        expect(result.current.people.length).toBe(3);
      });

      // Select all first
      act(() => {
        result.current.selectAll();
      });

      expect(result.current.selectedIds.size).toBe(3);

      const idsToDelete = ["person-1", "person-2"];

      await act(async () => {
        await result.current.bulkDelete(idsToDelete);
      });

      expect(result.current.selectedIds.size).toBe(1);
      expect(result.current.selectedIds.has("person-3")).toBe(true);
      expect(result.current.selectedIds.has("person-1")).toBe(false);
      expect(result.current.selectedIds.has("person-2")).toBe(false);
    });

    it("should remove deleted IDs from excludedIds", async () => {
      vi.mocked(peopleApi.getExcludePreferences).mockResolvedValueOnce({
        excluded_person_cluster_ids: ["person-1", "person-2"],
      });

      const { result } = renderHook(() => usePeople());

      await waitFor(() => {
        expect(result.current.excludedIds.size).toBe(2);
      });

      const idsToDelete = ["person-1"];

      await act(async () => {
        await result.current.bulkDelete(idsToDelete);
      });

      expect(result.current.excludedIds.size).toBe(1);
      expect(result.current.excludedIds.has("person-2")).toBe(true);
      expect(result.current.excludedIds.has("person-1")).toBe(false);
    });

    it("should handle API errors gracefully", async () => {
      const error = new Error("API Error");
      vi.mocked(peopleApi.bulkDeletePeople).mockRejectedValueOnce(error);

      const { result } = renderHook(() => usePeople());

      await waitFor(() => {
        expect(result.current.people.length).toBe(3);
      });

      const idsToDelete = ["person-1"];

      await act(async () => {
        await result.current.bulkDelete(idsToDelete);
      });

      // People should not be deleted on error
      expect(result.current.people.length).toBe(3);
      expect(result.current.error).toBeTruthy();
    });


  });
});
