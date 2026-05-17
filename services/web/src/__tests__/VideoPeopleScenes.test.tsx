import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import type { VideoScene } from "@/lib/types";

const mockGetAccessToken = vi.fn().mockResolvedValue("token");

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ getAccessToken: mockGetAccessToken }),
}));

vi.mock("@/features/search/hooks/useAgent", () => ({
  useAgent: () => ({ isAvailable: false }),
}));

vi.mock("@/components/SceneThumbnail", () => ({
  SceneThumbnail: ({ sceneId }: { sceneId?: string }) => (
    <div data-testid={`thumb-${sceneId}`} />
  ),
}));

vi.mock("@/components/people/AvatarThumbnail", () => ({
  AvatarThumbnail: ({ person }: { person: { person_cluster_id: string; label: string | null } }) => (
    <div data-testid={`avatar-${person.person_cluster_id}`}>{person.label}</div>
  ),
}));

vi.mock("@/features/people/components/DeletePersonDialog", () => ({
  DeletePersonDialog: () => null,
}));

vi.mock("@/lib/api/videos", () => ({
  getVideoPeople: vi.fn().mockResolvedValue({
    people: [
      {
        person_cluster_id: "person-a",
        label: "Alice",
        face_count: 2,
        last_seen_scene_time: null,
        representative_video_id: "vid-1",
        representative_scene_id: "s1",
        is_excluded: false,
      },
      {
        person_cluster_id: "person-b",
        label: "Bob",
        face_count: 1,
        last_seen_scene_time: null,
        representative_video_id: "vid-1",
        representative_scene_id: "s3",
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

vi.mock("@/features/people/components/MergeConfirmDialog", () => ({
  MergeConfirmDialog: ({
    source,
    target,
    onConfirm,
    onCancel,
  }: {
    source: { person_cluster_id: string; label: string | null };
    target: { person_cluster_id: string; label: string | null };
    isMerging: boolean;
    onConfirm: (keepLabel?: string | null) => void;
    onCancel: () => void;
  }) => (
    <div data-testid="merge-dialog">
      <span data-testid="merge-source">{source.person_cluster_id}</span>
      <span data-testid="merge-target">{target.person_cluster_id}</span>
      <button data-testid="merge-confirm" onClick={() => onConfirm(null)}>병합</button>
      <button data-testid="merge-cancel" onClick={onCancel}>취소</button>
    </div>
  ),
}));

function buildScene(id: string, startMs: number, personIds: string[]): VideoScene {
  return {
    scene_id: id,
    start_ms: startMs,
    end_ms: startMs + 10000,
    transcript_raw: `transcript for ${id}`,
    transcript_char_count: 20,
    keyword_tags: [],
    product_tags: [],
    product_entities: [],
    speech_segment_count: 0,
    people_cluster_ids: personIds,
    ingest_time: null,
    keyframe_timestamp_ms: startMs,
  };
}

const scenes: VideoScene[] = [
  buildScene("s1", 0, ["person-a"]),
  buildScene("s2", 10000, ["person-a", "person-b"]),
  buildScene("s3", 20000, ["person-b"]),
  buildScene("s4", 30000, []),
  buildScene("s5", 40000, ["person-a"]),
];

import { VideoPeoplePanel } from "@/features/videos/components/VideoPeoplePanel";

describe("VideoPeoplePanel scene integration", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("does not show scene grid when no avatar is selected", async () => {
    render(
      <VideoPeoplePanel videoId="vid-1" scenes={scenes} aspectRatio="16:9" />,
    );
    await waitFor(() => expect(screen.getByTestId("avatar-person-a")).toBeInTheDocument());
    expect(screen.queryByText("등장 장면")).not.toBeInTheDocument();
  });

  it("shows filtered scenes when avatar is clicked", async () => {
    const user = userEvent.setup();
    render(
      <VideoPeoplePanel videoId="vid-1" scenes={scenes} aspectRatio="16:9" />,
    );
    await waitFor(() => expect(screen.getByTestId("avatar-person-a")).toBeInTheDocument());

    await user.click(screen.getByTestId("avatar-person-a").closest("button")!);

    await waitFor(() => expect(screen.getByText("등장 장면")).toBeInTheDocument());
    expect(screen.getByText("(3개)")).toBeInTheDocument();
    expect(screen.getByTestId("thumb-s1")).toBeInTheDocument();
    expect(screen.getByTestId("thumb-s2")).toBeInTheDocument();
    expect(screen.getByTestId("thumb-s5")).toBeInTheDocument();
    expect(screen.queryByTestId("thumb-s3")).not.toBeInTheDocument();
    expect(screen.queryByTestId("thumb-s4")).not.toBeInTheDocument();
  });

  it("updates scene grid when different avatar is clicked", async () => {
    const user = userEvent.setup();
    render(
      <VideoPeoplePanel videoId="vid-1" scenes={scenes} aspectRatio="16:9" />,
    );
    await waitFor(() => expect(screen.getByTestId("avatar-person-a")).toBeInTheDocument());

    await user.click(screen.getByTestId("avatar-person-a").closest("button")!);
    await waitFor(() => expect(screen.getByText("(3개)")).toBeInTheDocument());

    await user.click(screen.getByTestId("avatar-person-a").closest("button")!);
    expect(screen.queryByText("등장 장면")).not.toBeInTheDocument();

    await user.click(screen.getByTestId("avatar-person-b").closest("button")!);
    await waitFor(() => expect(screen.getByText("(2개)")).toBeInTheDocument());
    expect(screen.getByTestId("thumb-s2")).toBeInTheDocument();
    expect(screen.getByTestId("thumb-s3")).toBeInTheDocument();
    expect(screen.queryByTestId("thumb-s1")).not.toBeInTheDocument();
  });

  it("shows empty state for person with no matching scenes", async () => {
    const scenesWithNoMatch: VideoScene[] = [
      buildScene("s1", 0, ["person-c"]),
    ];
    const user = userEvent.setup();
    render(
      <VideoPeoplePanel videoId="vid-1" scenes={scenesWithNoMatch} aspectRatio="16:9" />,
    );
    await waitFor(() => expect(screen.getByTestId("avatar-person-a")).toBeInTheDocument());

    await user.click(screen.getByTestId("avatar-person-a").closest("button")!);
    await waitFor(() =>
      expect(screen.getByText("이 영상에서 등장하는 장면이 없습니다.")).toBeInTheDocument(),
    );
  });

  it("calls onSeekToScene when scene thumbnail is clicked", async () => {
    const onSeek = vi.fn();
    const user = userEvent.setup();
    render(
      <VideoPeoplePanel
        videoId="vid-1"
        scenes={scenes}
        onSeekToScene={onSeek}
        aspectRatio="16:9"
      />,
    );
    await waitFor(() => expect(screen.getByTestId("avatar-person-a")).toBeInTheDocument());

    await user.click(screen.getByTestId("avatar-person-a").closest("button")!);
    await waitFor(() => expect(screen.getByTestId("thumb-s1")).toBeInTheDocument());

    await user.click(screen.getByTestId("thumb-s1").closest("button")!);
    expect(onSeek).toHaveBeenCalledWith(0);
  });

  it("does not render scene grid when scenes prop is not provided", async () => {
    const user = userEvent.setup();
    render(<VideoPeoplePanel videoId="vid-1" />);
    await waitFor(() => expect(screen.getByTestId("avatar-person-a")).toBeInTheDocument());

    await user.click(screen.getByTestId("avatar-person-a").closest("button")!);
    expect(screen.queryByText("등장 장면")).not.toBeInTheDocument();
  });

  it("does not show merge dialog initially", async () => {
    render(
      <VideoPeoplePanel videoId="vid-1" scenes={scenes} aspectRatio="16:9" />,
    );
    await waitFor(() => expect(screen.getByTestId("avatar-person-a")).toBeInTheDocument());
    expect(screen.queryByTestId("merge-dialog")).not.toBeInTheDocument();
  });

  it("calls mergePeople API when merge dialog is confirmed", async () => {
    const { mergePeople: mergePeopleApi } = await import("@/lib/api/people");
    const mockMerge = vi.mocked(mergePeopleApi);
    mockMerge.mockResolvedValueOnce({
      target_cluster_id: "person-b",
      merged_source_ids: ["person-a"],
      scenes_updated: 3,
      label: "Bob",
    });

    render(
      <VideoPeoplePanel videoId="vid-1" scenes={scenes} aspectRatio="16:9" />,
    );
    await waitFor(() => expect(screen.getByTestId("avatar-person-a")).toBeInTheDocument());
    expect(screen.queryByTestId("merge-dialog")).not.toBeInTheDocument();
    expect(mockMerge).not.toHaveBeenCalled();
  });

  it("hides merge dialog when cancel is clicked", async () => {
    render(
      <VideoPeoplePanel videoId="vid-1" scenes={scenes} aspectRatio="16:9" />,
    );
    await waitFor(() => expect(screen.getByTestId("avatar-person-a")).toBeInTheDocument());
    expect(screen.queryByTestId("merge-dialog")).not.toBeInTheDocument();
  });
});
