import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { SceneCard, ShortsCreatePage } from "@/features/shorts/components/ShortsCreatePage";
import { getVideoScenes } from "@/lib/api/videos";
import { parseSpeakerTranscript } from "@/lib/speaker-transcript";
import type { VideoScene, VideoScenesResponse } from "@/lib/types";

// ── Mocks ──────────────────────────────────────────────────────────────────

vi.mock("@/components/SceneThumbnail", () => ({
  SceneThumbnail: () => <div data-testid="scene-thumbnail" />,
}));

let mockVideoId: string | null = "video-test";
let mockSceneIds: string | null = null;
const mockRouterPush = vi.fn();
const mockGetAccessToken = vi.fn().mockResolvedValue("test-token");

vi.mock("next/navigation", () => ({
  useSearchParams: () => ({
    get: (k: string) => {
      if (k === "videoId") return mockVideoId;
      if (k === "sceneIds") return mockSceneIds;
      return null;
    },
  }),
  useRouter: () => ({ push: mockRouterPush }),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    getAccessToken: mockGetAccessToken,
    isAuthenticated: true,
    isLoading: false,
    user: { email: "test@test.com", name: "Test" },
    error: null,
    login: vi.fn(),
    loginWithCredentials: vi.fn(),
    logout: vi.fn(),
    isAuth0Enabled: false,
  }),
}));

vi.mock("@/lib/api/videos", () => ({
  getVideoScenes: vi.fn(),
}));

vi.mock("@/lib/agent", () => ({
  getAgentPlaybackUrl: vi.fn().mockReturnValue("http://agent/video"),
  getCloudPlaybackUrl: vi.fn().mockReturnValue("http://cloud/video"),
}));

// ── Fixtures ───────────────────────────────────────────────────────────────

const baseScene: VideoScene = {
  scene_id: "scene-1",
  start_ms: 0,
  end_ms: 10000,
  transcript_raw: "",
  transcript_char_count: 0,
  keyword_tags: [],
  product_tags: [],
  product_entities: [],
  speech_segment_count: 0,
  people_cluster_ids: [],
  ingest_time: null,
  keyframe_timestamp_ms: 0,
};

const defaultCardProps = {
  scene: baseScene,
  index: 0,
  videoId: "video-test",
  selected: false,
  onToggle: vi.fn(),
};

const makeResponse = (scenes: VideoScene[]): VideoScenesResponse => ({
  video_id: "video-test",
  video_title: "Test Video",
  source_type: "agent",
  source_path: null,
  library_name: null,
  capture_time: null,
  earliest_ingest_time: null,
  scenes,
  total: scenes.length,
});

beforeEach(() => {
  vi.clearAllMocks();
  mockVideoId = "video-test";
  mockSceneIds = null;
});

// ── Tests: scene_caption rendering ───────────────────────────────────────

describe("SceneCard scene_caption rendering", () => {
  it("renders scene_caption when present", () => {
    const scene = { ...baseScene, scene_caption: "이것은 요약입니다" };
    render(<SceneCard {...defaultCardProps} scene={scene} />);
    expect(screen.getByText("이것은 요약입니다")).toBeInTheDocument();
  });

  it("does NOT render scene_caption when undefined", () => {
    render(<SceneCard {...defaultCardProps} scene={{ ...baseScene, scene_caption: undefined }} />);
    expect(screen.queryByText("이것은 요약입니다")).not.toBeInTheDocument();
  });

  it("does NOT render scene_caption when empty string", () => {
    render(<SceneCard {...defaultCardProps} scene={{ ...baseScene, scene_caption: "" }} />);
    const captionPs = screen
      .queryAllByText(/.+/)
      .filter((el) => el.tagName === "P" && el.classList.contains("text-gray-600"));
    expect(captionPs).toHaveLength(0);
  });

  it("truncates scene_caption longer than 70 characters", () => {
    const longCaption = "가".repeat(80);
    render(<SceneCard {...defaultCardProps} scene={{ ...baseScene, scene_caption: longCaption }} />);
    expect(screen.getByText("가".repeat(70) + "…")).toBeInTheDocument();
  });
});

// ── Tests: parseSpeakerTranscript ────────────────────────────────────────

describe("parseSpeakerTranscript", () => {
  it("returns empty array for empty string", () => {
    expect(parseSpeakerTranscript("")).toEqual([]);
  });

  it("returns empty array for null/undefined", () => {
    expect(parseSpeakerTranscript(null)).toEqual([]);
    expect(parseSpeakerTranscript(undefined)).toEqual([]);
  });

  it("parses single speaker line", () => {
    const result = parseSpeakerTranscript("SPEAKER_00 [0:00]: 안녕하세요");
    expect(result).toHaveLength(1);
    expect(result[0].text).toBe("안녕하세요");
    expect(result[0].label).toBe("A");
    expect(result[0].timestamp).toBe("0:00");
  });

  it("parses multi-speaker multi-line", () => {
    const input = [
      "SPEAKER_00 [0:00]: 안녕하세요",
      "SPEAKER_01 [0:15]: 네 감사합니다",
      "SPEAKER_00 [1:30]: 이 제품을 봐주세요",
    ].join("\n");
    const result = parseSpeakerTranscript(input);
    expect(result).toHaveLength(3);
    expect(result[0].label).toBe("A");
    expect(result[1].label).toBe("B");
    expect(result[2].label).toBe("A");
  });

  it("converts SPEAKER_00 → A, SPEAKER_01 → B", () => {
    const input = "SPEAKER_00 [0:00]: first\nSPEAKER_01 [0:10]: second";
    const result = parseSpeakerTranscript(input);
    expect(result[0].label).toBe("A");
    expect(result[1].label).toBe("B");
  });

  it("handles UNKNOWN speaker → assigns next available label", () => {
    const result = parseSpeakerTranscript("UNKNOWN [0:00]: some text");
    expect(result).toHaveLength(1);
    expect(result[0].label).toBe("A");
    expect(result[0].rawId).toBe("UNKNOWN");
  });
});

// ── Tests: SceneCard speaker transcript rendering ────────────────────────

describe("SceneCard speaker_transcript rendering", () => {
  it("renders speaker badge, timestamp, and text when speaker_transcript present", () => {
    const scene = {
      ...baseScene,
      speaker_transcript: "SPEAKER_00 [0:02]: 안녕하세요 여러분",
    };
    render(<SceneCard {...defaultCardProps} scene={scene} />);
    expect(screen.getByText("A")).toBeInTheDocument();
    expect(screen.getByText("00:00:02")).toBeInTheDocument();
    expect(screen.getByText("안녕하세요 여러분")).toBeInTheDocument();
  });

  it("renders absolute timestamp (scene start + speaker offset)", () => {
    const scene = {
      ...baseScene,
      start_ms: 61000, // 00:01:01
      speaker_transcript: "SPEAKER_00 [0:05]: 안녕하세요",
    };
    render(<SceneCard {...defaultCardProps} scene={scene} />);
    // 00:01:01 + 0:05 = 00:01:06
    expect(screen.getByText("00:01:06")).toBeInTheDocument();
  });

  it("renders absolute timestamp with HH:MM:SS offset format", () => {
    const scene = {
      ...baseScene,
      start_ms: 0,
      speaker_transcript: "SPEAKER_00 [1:02:03]: 테스트",
    };
    render(<SceneCard {...defaultCardProps} scene={scene} />);
    // 0 + 1:02:03 (3723s) = 01:02:03
    expect(screen.getByText("01:02:03")).toBeInTheDocument();
  });

  it("shows max 2 speaker entries", () => {
    const scene = {
      ...baseScene,
      speaker_transcript: [
        "SPEAKER_00 [0:00]: first line",
        "SPEAKER_01 [0:10]: second line",
        "SPEAKER_00 [0:20]: third line",
      ].join("\n"),
    };
    render(<SceneCard {...defaultCardProps} scene={scene} />);
    expect(screen.getByText("first line")).toBeInTheDocument();
    expect(screen.getByText("second line")).toBeInTheDocument();
    expect(screen.queryByText("third line")).not.toBeInTheDocument();
  });

  it("truncates speaker text at 100 characters", () => {
    const longText = "나".repeat(110);
    const scene = {
      ...baseScene,
      speaker_transcript: `SPEAKER_00 [0:00]: ${longText}`,
    };
    render(<SceneCard {...defaultCardProps} scene={scene} />);
    expect(screen.getByText("나".repeat(100) + "…")).toBeInTheDocument();
  });

  it("falls back to transcript_raw when speaker_transcript is empty", () => {
    const scene = {
      ...baseScene,
      speaker_transcript: "",
      transcript_raw: "일반 자막 텍스트",
    };
    render(<SceneCard {...defaultCardProps} scene={scene} />);
    expect(screen.getByText("일반 자막 텍스트")).toBeInTheDocument();
  });

  it("shows nothing when both speaker_transcript and transcript_raw are empty", () => {
    const scene = {
      ...baseScene,
      speaker_transcript: "",
      transcript_raw: "",
    };
    render(<SceneCard {...defaultCardProps} scene={scene} />);
    // No speaker entries or transcript text rendered
    expect(screen.queryByText("A")).not.toBeInTheDocument();
  });
});

// ── Tests: SceneCard baseline ──────────────────────────────────────────────

describe("SceneCard baseline", () => {
  it("renders scene number label 장면1 and 장면2", () => {
    const { unmount } = render(<SceneCard {...defaultCardProps} index={0} />);
    expect(screen.getByText("장면1")).toBeInTheDocument();
    unmount();

    render(<SceneCard {...defaultCardProps} index={1} />);
    expect(screen.getByText("장면2")).toBeInTheDocument();
  });

  it("renders formatted time range in HH:MM:SS format", () => {
    render(<SceneCard {...defaultCardProps} />);
    expect(screen.getByText("00:00:00 - 00:00:10")).toBeInTheDocument();
  });

  it("renders keyword_tags and product_tags (up to 2)", () => {
    const scene = {
      ...baseScene,
      keyword_tags: ["패션", "언박싱"],
      product_tags: ["상품A"],
    };
    render(<SceneCard {...defaultCardProps} scene={scene} />);
    expect(screen.getByText("패션")).toBeInTheDocument();
    expect(screen.getByText("언박싱")).toBeInTheDocument();
    // slice(0, 2) → 상품A is cut off
    expect(screen.queryByText("상품A")).not.toBeInTheDocument();
  });

  it("does NOT render tag section when no tags", () => {
    render(<SceneCard {...defaultCardProps} />);
    expect(screen.queryByText("패션")).not.toBeInTheDocument();
  });

  it("selected scene card has indigo ring class", () => {
    render(<SceneCard {...defaultCardProps} selected={true} />);
    const card = screen.getByRole("button");
    expect(card).toHaveClass("ring-1");
  });

  it("unselected scene card has default border class", () => {
    render(<SceneCard {...defaultCardProps} selected={false} />);
    const card = screen.getByRole("button");
    expect(card).not.toHaveClass("ring-1");
    expect(card).toHaveClass("border-gray-200");
  });

  it("checkbox is in title row (not on thumbnail) with Figma styles", () => {
    render(<SceneCard {...defaultCardProps} selected={false} />);
    const checkbox = screen.getByTestId("scene-checkbox");
    // Checkbox is inside the content panel, not inside the thumbnail wrapper
    expect(checkbox.closest("[data-testid='scene-thumbnail']")).toBeNull();
    // Figma styles: 16.5px square, rounded-[4px], unselected border
    expect(checkbox).toHaveClass("size-[16.5px]", "rounded-[4px]");
    expect(checkbox).toHaveClass("bg-white", "border-[#c7c7c7]");
  });

  it("selected checkbox shows check icon with #605dec background", () => {
    render(<SceneCard {...defaultCardProps} selected={true} />);
    const checkbox = screen.getByTestId("scene-checkbox");
    expect(checkbox).toHaveClass("bg-[#605dec]");
    expect(checkbox.querySelector("svg")).toBeInTheDocument();
  });

  it("unselected checkbox does not show check icon", () => {
    render(<SceneCard {...defaultCardProps} selected={false} />);
    const checkbox = screen.getByTestId("scene-checkbox");
    expect(checkbox.querySelector("svg")).not.toBeInTheDocument();
  });

  it("clicking a scene card calls onToggle", async () => {
    const onToggle = vi.fn();
    const user = userEvent.setup();
    render(<SceneCard {...defaultCardProps} onToggle={onToggle} />);
    await user.click(screen.getByRole("button"));
    expect(onToggle).toHaveBeenCalled();
  });
});

// ── Tests: ShortsCreatePage behavior ──────────────────────────────────────

describe("ShortsCreatePage behavior", () => {
  it("shows loading spinner while getVideoScenes is pending", () => {
    vi.mocked(getVideoScenes).mockImplementation(() => new Promise(() => undefined));
    const { container } = render(<ShortsCreatePage />);
    expect(container.querySelector(".animate-spin")).toBeInTheDocument();
  });

  it("shows 영상을 선택해 주세요 when videoId is absent", () => {
    mockVideoId = null;
    render(<ShortsCreatePage />);
    expect(screen.getByText("영상을 선택해 주세요.")).toBeInTheDocument();
  });

  it("shows 장면이 없습니다 when API returns empty scenes", async () => {
    vi.mocked(getVideoScenes).mockResolvedValue(makeResponse([]));
    render(<ShortsCreatePage />);
    expect(await screen.findByText("장면이 없습니다.")).toBeInTheDocument();
  });

  it("전체 선택 button selects all scenes", async () => {
    const scene2 = { ...baseScene, scene_id: "scene-2", start_ms: 10000, end_ms: 20000 };
    vi.mocked(getVideoScenes).mockResolvedValue(makeResponse([baseScene, scene2]));

    const user = userEvent.setup();
    render(<ShortsCreatePage />);
    await screen.findByText("장면1");

    await user.click(screen.getByRole("button", { name: "전체 선택" }));

    const cards = screen.getAllByRole("button", { name: /장면/ });
    cards.forEach((card) => expect(card).toHaveClass("ring-1"));
  });

  it("전체 해제 button deselects all when all are selected", async () => {
    const scene2 = { ...baseScene, scene_id: "scene-2", start_ms: 10000, end_ms: 20000 };
    vi.mocked(getVideoScenes).mockResolvedValue(makeResponse([baseScene, scene2]));

    const user = userEvent.setup();
    render(<ShortsCreatePage />);
    await screen.findByText("장면1");

    await user.click(screen.getByRole("button", { name: "전체 선택" }));
    await user.click(screen.getByRole("button", { name: "전체 해제" }));

    const cards = screen.getAllByRole("button", { name: /장면/ });
    cards.forEach((card) => expect(card).not.toHaveClass("ring-1"));
  });

  it("selected scenes summary panel appears when at least one scene selected", async () => {
    vi.mocked(getVideoScenes).mockResolvedValue(makeResponse([baseScene]));

    const user = userEvent.setup();
    render(<ShortsCreatePage />);
    const card = await screen.findByRole("button", { name: /장면1/ });

    expect(screen.queryByText(/선택된 장면/)).not.toBeInTheDocument();

    await user.click(card);
    expect(screen.getByText(/선택된 장면/)).toBeInTheDocument();
  });

  it("저장하기 button is disabled when no scenes selected, enabled when selected", async () => {
    vi.mocked(getVideoScenes).mockResolvedValue(makeResponse([baseScene]));

    const user = userEvent.setup();
    render(<ShortsCreatePage />);
    await screen.findByText("장면1");

    const saveBtn = screen.getByRole("button", { name: /저장하기/ });
    expect(saveBtn).toBeDisabled();

    await user.click(screen.getByRole("button", { name: /장면1/ }));
    await waitFor(() => {
      expect(screen.getByRole("button", { name: /저장하기/ })).not.toBeDisabled();
    });
  });

  it("pre-selects scenes when sceneIds query param is provided", async () => {
    mockSceneIds = "scene-1";
    vi.mocked(getVideoScenes).mockResolvedValue(makeResponse([baseScene]));

    render(<ShortsCreatePage />);
    await screen.findByText("장면1");

    const card = screen.getByRole("button", { name: /장면1/ });
    expect(card).toHaveClass("ring-1");
  });

  it("deselects a scene when clicking a selected scene card", async () => {
    const scene2 = { ...baseScene, scene_id: "scene-2", start_ms: 10000, end_ms: 20000 };
    vi.mocked(getVideoScenes).mockResolvedValue(makeResponse([baseScene, scene2]));

    const user = userEvent.setup();
    render(<ShortsCreatePage />);
    await screen.findByText("장면1");

    // Select all, then deselect scene-1
    await user.click(screen.getByRole("button", { name: "전체 선택" }));
    const cards = screen.getAllByRole("button", { name: /장면/ });
    expect(cards[0]).toHaveClass("ring-1");

    await user.click(cards[0]);
    await waitFor(() => {
      const updated = screen.getAllByRole("button", { name: /장면/ });
      expect(updated[0]).not.toHaveClass("ring-1");
      // scene-2 should still be selected
      expect(updated[1]).toHaveClass("ring-1");
    });
  });

  it("saves successfully and navigates to /shorts", async () => {
    vi.mocked(getVideoScenes).mockResolvedValue(makeResponse([baseScene]));
    vi.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ id: "short-1" }), { status: 201 }),
    );

    const user = userEvent.setup();
    render(<ShortsCreatePage />);
    await screen.findByText("장면1");

    await user.click(screen.getByRole("button", { name: /장면1/ }));
    await user.click(screen.getByRole("button", { name: /저장하기/ }));

    await waitFor(() => {
      expect(mockRouterPush).toHaveBeenCalledWith("/shorts");
    });

    vi.mocked(global.fetch).mockRestore();
  });

  it("shows error message when save fails with detail", async () => {
    vi.mocked(getVideoScenes).mockResolvedValue(makeResponse([baseScene]));
    vi.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response(JSON.stringify({ detail: "권한 없음" }), { status: 403 }),
    );

    const user = userEvent.setup();
    render(<ShortsCreatePage />);
    await screen.findByText("장면1");

    await user.click(screen.getByRole("button", { name: /장면1/ }));
    await user.click(screen.getByRole("button", { name: /저장하기/ }));

    expect(await screen.findByText("권한 없음")).toBeInTheDocument();

    vi.mocked(global.fetch).mockRestore();
  });

  it("shows fallback error when save fails without detail", async () => {
    vi.mocked(getVideoScenes).mockResolvedValue(makeResponse([baseScene]));
    vi.spyOn(global, "fetch").mockResolvedValueOnce(
      new Response("bad", { status: 500, headers: { "Content-Type": "text/plain" } }),
    );

    const user = userEvent.setup();
    render(<ShortsCreatePage />);
    await screen.findByText("장면1");

    await user.click(screen.getByRole("button", { name: /장면1/ }));
    await user.click(screen.getByRole("button", { name: /저장하기/ }));

    expect(await screen.findByText("저장 실패 (500)")).toBeInTheDocument();

    vi.mocked(global.fetch).mockRestore();
  });

  it("shows generic error when fetch throws", async () => {
    vi.mocked(getVideoScenes).mockResolvedValue(makeResponse([baseScene]));
    vi.spyOn(global, "fetch").mockRejectedValueOnce("network error");

    const user = userEvent.setup();
    render(<ShortsCreatePage />);
    await screen.findByText("장면1");

    await user.click(screen.getByRole("button", { name: /장면1/ }));
    await user.click(screen.getByRole("button", { name: /저장하기/ }));

    expect(await screen.findByText("저장 중 오류가 발생했습니다.")).toBeInTheDocument();

    vi.mocked(global.fetch).mockRestore();
  });

  it("handles API error gracefully (getVideoScenes rejects)", async () => {
    vi.mocked(getVideoScenes).mockRejectedValueOnce(new Error("API error"));

    render(<ShortsCreatePage />);

    expect(await screen.findByText("장면이 없습니다.")).toBeInTheDocument();
  });

  it("renders gdrive playback URL when source_type is gdrive", async () => {
    const gdriveResponse: VideoScenesResponse = {
      ...makeResponse([baseScene]),
      source_type: "gdrive",
    };
    vi.mocked(getVideoScenes).mockResolvedValue(gdriveResponse);

    render(<ShortsCreatePage />);
    await screen.findByText("장면1");

    const video = document.querySelector("video");
    expect(video?.src).toContain("cloud");
  });
});
