import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { StatsBar } from "@/features/videos/components/StatsBar";
import { VideoCard } from "@/features/videos/components/VideoCard";
import { VideoList } from "@/features/videos/components/VideoList";
import { VideoFilterPanel } from "@/features/videos/components/VideoFilterPanel";
import { VideoDetailDrawer } from "@/features/videos/components/VideoDetailDrawer";
import type {
  VideoSummary,
  VideoScene,
  VideoStats,
  VideoFacets,
} from "@/lib/types";

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    getAccessToken: vi.fn().mockResolvedValue("test-token"),
    isAuthenticated: true,
    isLoading: false,
    user: { email: "test@test.com", name: "Test" },
    error: null,
    login: vi.fn(),
    logout: vi.fn(),
    isAuth0Enabled: false,
  }),
}));

const sampleVideo: VideoSummary = {
  video_id: "video-abc-123",
  video_title: "Spring Campaign",
  library_id: "lib-1",
  library_name: "Main Library",
  source_type: "gdrive",
  scene_count: 5,
  first_scene_start_ms: 0,
  last_scene_end_ms: 120000,
  earliest_ingest_time: "2025-02-10T10:00:00Z",
  latest_ingest_time: "2025-02-10T12:00:00Z",
  keyword_tags: ["fashion", "unboxing"],
  product_tags: ["product-a"],
  people_count: 2,
  required_drive_nickname: null,
  source_path: null,
  first_scene_keyframe_ms: 0,
};

const sampleStats: VideoStats = {
  total_videos: 42,
  total_scenes: 350,
  total_libraries: 3,
  source_breakdown: { gdrive: 30, removable_disk: 12 },
  latest_ingest_time: "2025-02-10T12:00:00Z",
  scenes_last_24h: 15,
  scenes_last_7d: 100,
};

const sampleScene: VideoScene = {
  scene_id: "video-abc-123_scene_0",
  start_ms: 0,
  end_ms: 30000,
  transcript_raw: "Hello everyone, welcome to the live show.",
  transcript_char_count: 42,
  keyword_tags: ["greeting"],
  product_tags: [],
  product_entities: [],
  speech_segment_count: 3,
  people_cluster_ids: ["p1"],
  ingest_time: "2025-02-10T10:00:00Z",
  keyframe_timestamp_ms: 0,
};

const sampleFacets: VideoFacets = {
  libraries: [
    { id: "lib-1", name: "Main Library", count: 30 },
    { id: "lib-2", name: "Backup", count: 12 },
  ],
  source_types: [
    { id: "gdrive", name: null, count: 30 },
    { id: "removable_disk", name: null, count: 12 },
  ],
};

// ---------------------------------------------------------------------------
// StatsBar
// ---------------------------------------------------------------------------
describe("StatsBar", () => {
  it("renders stat values when loaded", () => {
    render(<StatsBar stats={sampleStats} isLoading={false} />);
    expect(screen.getByText("42")).toBeInTheDocument();
    expect(screen.getByText("350")).toBeInTheDocument();
    expect(screen.getByText("3")).toBeInTheDocument();
    expect(screen.getByText("15")).toBeInTheDocument();
  });

  it("renders labels", () => {
    render(<StatsBar stats={sampleStats} isLoading={false} />);
    expect(screen.getByText("Total Videos")).toBeInTheDocument();
    expect(screen.getByText("Total Scenes")).toBeInTheDocument();
    expect(screen.getByText("Libraries")).toBeInTheDocument();
    expect(screen.getByText("Scenes (24h)")).toBeInTheDocument();
  });

  it("renders loading skeleton when isLoading", () => {
    const { container } = render(<StatsBar stats={null} isLoading={true} />);
    const pulseElements = container.querySelectorAll(".animate-pulse");
    expect(pulseElements.length).toBe(4);
  });
});

// ---------------------------------------------------------------------------
// VideoCard
// ---------------------------------------------------------------------------
describe("VideoCard", () => {
  it("renders video id and library name", () => {
    render(<VideoCard video={sampleVideo} onSelect={vi.fn()} agentAvailable={false} />);
    expect(screen.getByText("Spring Campaign")).toBeInTheDocument();
    expect(screen.getByText("Main Library")).toBeInTheDocument();
  });

  it("renders scene count", () => {
    render(<VideoCard video={sampleVideo} onSelect={vi.fn()} agentAvailable={false} />);
    expect(screen.getByText("5 scenes")).toBeInTheDocument();
  });

  it("renders source type badge", () => {
    render(<VideoCard video={sampleVideo} onSelect={vi.fn()} agentAvailable={false} />);
    expect(screen.getByText("Drive")).toBeInTheDocument();
  });

  it("renders keyword and product tags", () => {
    render(<VideoCard video={sampleVideo} onSelect={vi.fn()} agentAvailable={false} />);
    expect(screen.getByText("fashion")).toBeInTheDocument();
    expect(screen.getByText("unboxing")).toBeInTheDocument();
    expect(screen.getByText("product-a")).toBeInTheDocument();
  });

  it("calls onSelect when clicked", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(<VideoCard video={sampleVideo} onSelect={onSelect} agentAvailable={false} />);
    await user.click(screen.getByText("Spring Campaign"));
    expect(onSelect).toHaveBeenCalledWith("video-abc-123");
  });

   it("renders removable_disk source type", () => {
     const diskVideo = { ...sampleVideo, source_type: "removable_disk" as const, first_scene_keyframe_ms: 0 };
     render(<VideoCard video={diskVideo} onSelect={vi.fn()} agentAvailable={false} />);
     expect(screen.getByText("Disk")).toBeInTheDocument();
   });
});

// ---------------------------------------------------------------------------
// VideoList
// ---------------------------------------------------------------------------
describe("VideoList", () => {
  const defaultProps = {
    videos: [] as VideoSummary[],
    isLoading: false,
    isLoadingMore: false,
    hasMore: false,
    total: 0,
    onSelect: vi.fn(),
    onLoadMore: vi.fn(),
    agentAvailable: false,
  };

  it("shows empty state when no videos", () => {
    render(<VideoList {...defaultProps} />);
    expect(screen.getByText("No videos ingested yet")).toBeInTheDocument();
  });

  it("renders loading skeletons", () => {
    const { container } = render(<VideoList {...defaultProps} isLoading={true} />);
    const pulseElements = container.querySelectorAll(".animate-pulse");
    expect(pulseElements.length).toBe(5);
  });

   it("renders multiple video cards", () => {
     const videos = [
       sampleVideo,
       {
         ...sampleVideo,
         video_id: "video-def-456",
         video_title: "Winter Campaign",
         library_name: "Other Library",
         first_scene_keyframe_ms: 0,
       },
     ];
    render(<VideoList {...defaultProps} videos={videos} total={2} />);
    expect(screen.getByText("Spring Campaign")).toBeInTheDocument();
    expect(screen.getByText("Winter Campaign")).toBeInTheDocument();
    expect(screen.getByText("Showing 2 of 2 videos")).toBeInTheDocument();
  });

  it("shows Load More button when hasMore", () => {
    render(
      <VideoList {...defaultProps} videos={[sampleVideo]} total={10} hasMore={true} />,
    );
    expect(screen.getByText("Load More")).toBeInTheDocument();
  });

  it("calls onLoadMore when Load More clicked", async () => {
    const onLoadMore = vi.fn();
    const user = userEvent.setup();
    render(
      <VideoList
        {...defaultProps}
        videos={[sampleVideo]}
        total={10}
        hasMore={true}
        onLoadMore={onLoadMore}
      />,
    );
    await user.click(screen.getByText("Load More"));
    expect(onLoadMore).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// VideoFilterPanel
// ---------------------------------------------------------------------------
describe("VideoFilterPanel", () => {
  it("renders sort options", () => {
    render(
      <VideoFilterPanel
        facets={sampleFacets}
        filters={{ sort: "latest" }}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText("Newest first")).toBeInTheDocument();
    expect(screen.getByText("Oldest first")).toBeInTheDocument();
  });

  it("renders library filter options", () => {
    render(
      <VideoFilterPanel
        facets={sampleFacets}
        filters={{ sort: "latest" }}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByText("All libraries")).toBeInTheDocument();
    expect(screen.getByText(/Main Library/)).toBeInTheDocument();
    expect(screen.getByText(/Backup/)).toBeInTheDocument();
  });

  it("calls onChange when sort changed", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <VideoFilterPanel
        facets={sampleFacets}
        filters={{ sort: "latest" }}
        onChange={onChange}
      />,
    );
    await user.click(screen.getByText("Oldest first"));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ sort: "oldest" }));
  });

  it("calls onChange when library selected", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <VideoFilterPanel
        facets={sampleFacets}
        filters={{ sort: "latest" }}
        onChange={onChange}
      />,
    );
    await user.click(screen.getByText(/Backup/));
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ library_id: "lib-2" }));
  });
});

// ---------------------------------------------------------------------------
// VideoDetailDrawer
// ---------------------------------------------------------------------------
describe("VideoDetailDrawer", () => {
  const defaultProps = {
    video: sampleVideo,
    scenes: [sampleScene],
    totalScenes: 1,
    isOpen: true,
    isLoading: false,
    onClose: vi.fn(),
    agentAvailable: false,
  };

  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("renders video id and library name", () => {
    render(<VideoDetailDrawer {...defaultProps} />);
    expect(screen.getByText("Spring Campaign")).toBeInTheDocument();
    expect(screen.getByText("Main Library")).toBeInTheDocument();
  });

  it("renders scene list with transcript", () => {
    render(<VideoDetailDrawer {...defaultProps} />);
    expect(
      screen.getByText("Hello everyone, welcome to the live show."),
    ).toBeInTheDocument();
  });

  it("renders scene time range", () => {
    render(<VideoDetailDrawer {...defaultProps} />);
    expect(screen.getByText("0:00 - 0:30")).toBeInTheDocument();
  });

  it("calls onClose when close button clicked", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<VideoDetailDrawer {...defaultProps} onClose={onClose} />);
    await user.click(screen.getByLabelText("Close"));
    expect(onClose).toHaveBeenCalled();
  });

  it("renders nothing when isOpen is false", () => {
    const { container } = render(
      <VideoDetailDrawer {...defaultProps} isOpen={false} />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("renders loading state for scenes", () => {
    const { container } = render(
      <VideoDetailDrawer {...defaultProps} scenes={[]} isLoading={true} />,
    );
    const pulseElements = container.querySelectorAll(".animate-pulse");
    expect(pulseElements.length).toBeGreaterThan(0);
  });

  it("shows scene tags", () => {
    render(<VideoDetailDrawer {...defaultProps} />);
    expect(screen.getByText("greeting")).toBeInTheDocument();
  });
});
