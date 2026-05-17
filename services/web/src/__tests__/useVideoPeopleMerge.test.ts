import { describe, expect, it, vi, beforeEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import * as peopleApi from "@/lib/api/people";
import { useVideoPeople } from "@/features/videos/hooks/useVideoPeople";

const mockGetAccessToken = vi.fn().mockResolvedValue("token");

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ getAccessToken: mockGetAccessToken }),
}));

vi.mock("@/lib/api/videos", () => ({
  getVideoPeople: vi.fn().mockResolvedValue({
    video_id: "v1",
    people: [
      {
        person_cluster_id: "p1",
        label: "Alice",
        face_count: 5,
        last_seen_scene_time: null,
        representative_video_id: "v1",
        representative_scene_id: "s1",
        is_excluded: false,
      },
      {
        person_cluster_id: "p2",
        label: "Bob",
        face_count: 3,
        last_seen_scene_time: null,
        representative_video_id: "v1",
        representative_scene_id: "s2",
        is_excluded: false,
      },
    ],
    total: 2,
  }),
}));

vi.mock("@/lib/api/people", () => ({
  renamePerson: vi.fn(),
  deletePerson: vi.fn(),
  mergePeople: vi.fn(),
}));

describe("useVideoPeople merge", () => {
  beforeEach(() => {
    vi.mocked(peopleApi.mergePeople).mockReset();
  });

  it("exposes mergePeople and isMerging", async () => {
    const { result } = renderHook(() => useVideoPeople("v1"));
    await waitFor(() => expect(result.current.people.length).toBe(2));
    expect(typeof result.current.mergePeople).toBe("function");
    expect(result.current.isMerging).toBe(false);
  });

  it("optimistically removes source cluster and updates target label", async () => {
    vi.mocked(peopleApi.mergePeople).mockResolvedValueOnce({
      target_cluster_id: "p2",
      merged_source_ids: ["p1"],
      scenes_updated: 5,
      label: "Bob",
    });

    const { result } = renderHook(() => useVideoPeople("v1"));
    await waitFor(() => expect(result.current.people.length).toBe(2));

    await act(async () => {
      const response = await result.current.mergePeople({
        source_cluster_ids: ["p1"],
        target_cluster_id: "p2",
      });
      expect(response).not.toBeNull();
      expect(response!.target_cluster_id).toBe("p2");
      expect(response!.merged_source_ids).toEqual(["p1"]);
    });

    expect(vi.mocked(peopleApi.mergePeople)).toHaveBeenCalledWith(
      { source_cluster_ids: ["p1"], target_cluster_id: "p2" },
      expect.any(Function),
    );
  });

  it("returns null and sets error on merge failure", async () => {
    vi.mocked(peopleApi.mergePeople).mockRejectedValueOnce(new Error("fail"));

    const { result } = renderHook(() => useVideoPeople("v1"));
    await waitFor(() => expect(result.current.people.length).toBe(2));

    await act(async () => {
      const response = await result.current.mergePeople({
        source_cluster_ids: ["p1"],
        target_cluster_id: "p2",
      });
      expect(response).toBeNull();
    });

    expect(result.current.error).toBe("인물 병합에 실패했습니다.");
    expect(result.current.people.length).toBe(2);
  });

  it("resets isMerging to false after merge completes", async () => {
    vi.mocked(peopleApi.mergePeople).mockResolvedValueOnce({
      target_cluster_id: "p2",
      merged_source_ids: ["p1"],
      scenes_updated: 3,
      label: "Bob",
    });

    const { result } = renderHook(() => useVideoPeople("v1"));
    await waitFor(() => expect(result.current.people.length).toBe(2));

    await act(async () => {
      await result.current.mergePeople({
        source_cluster_ids: ["p1"],
        target_cluster_id: "p2",
      });
    });

    expect(result.current.isMerging).toBe(false);
  });
});
