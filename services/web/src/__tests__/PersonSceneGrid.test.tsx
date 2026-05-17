import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { PersonSceneGrid } from "@/features/videos/components/PersonSceneGrid";
import type { VideoScene } from "@/lib/types";

vi.mock("@/components/SceneThumbnail", () => ({
  SceneThumbnail: ({ videoId, sceneId }: { videoId: string; sceneId?: string }) => (
    <div data-testid={`thumb-${sceneId}`} data-video-id={videoId} />
  ),
}));

function buildScene(overrides: Partial<VideoScene> & { scene_id: string; start_ms: number }): VideoScene {
  return {
    end_ms: overrides.start_ms + 10000,
    transcript_raw: "",
    transcript_char_count: 0,
    keyword_tags: [],
    product_tags: [],
    product_entities: [],
    speech_segment_count: 0,
    people_cluster_ids: [],
    ingest_time: null,
    keyframe_timestamp_ms: overrides.start_ms,
    ...overrides,
  };
}

const defaultProps = {
  videoId: "vid-1",
  agentAvailable: false,
  aspectRatio: "16:9" as const,
};

describe("PersonSceneGrid", () => {
  describe("empty state", () => {
    it("shows empty message when no scenes provided", () => {
      render(<PersonSceneGrid {...defaultProps} scenes={[]} />);
      expect(screen.getByText("이 영상에서 등장하는 장면이 없습니다.")).toBeInTheDocument();
    });

    it("shows header without count badge when empty", () => {
      render(<PersonSceneGrid {...defaultProps} scenes={[]} />);
      expect(screen.getByText("등장 장면")).toBeInTheDocument();
      expect(screen.queryByText(/개\)/)).not.toBeInTheDocument();
    });
  });

  describe("scene rendering", () => {
    const scenes = [
      buildScene({ scene_id: "s1", start_ms: 0, scene_caption: "첫 번째 장면 캡션" }),
      buildScene({ scene_id: "s2", start_ms: 30000, transcript_raw: "두 번째 장면 자막 텍스트" }),
      buildScene({ scene_id: "s3", start_ms: 65000 }),
    ];

    it("renders header with count badge", () => {
      render(<PersonSceneGrid {...defaultProps} scenes={scenes} />);
      expect(screen.getByText("등장 장면")).toBeInTheDocument();
      expect(screen.getByText("(3개)")).toBeInTheDocument();
    });

    it("renders one thumbnail per scene", () => {
      render(<PersonSceneGrid {...defaultProps} scenes={scenes} />);
      expect(screen.getByTestId("thumb-s1")).toBeInTheDocument();
      expect(screen.getByTestId("thumb-s2")).toBeInTheDocument();
      expect(screen.getByTestId("thumb-s3")).toBeInTheDocument();
    });

    it("shows formatted timestamp on each cell", () => {
      render(<PersonSceneGrid {...defaultProps} scenes={scenes} />);
      expect(screen.getByText("0:00")).toBeInTheDocument();
      expect(screen.getByText("0:30")).toBeInTheDocument();
      expect(screen.getByText("1:05")).toBeInTheDocument();
    });

    it("shows caption text, preferring scene_caption over transcript", () => {
      render(<PersonSceneGrid {...defaultProps} scenes={scenes} />);
      expect(screen.getByText("첫 번째 장면 캡션")).toBeInTheDocument();
      expect(screen.getByText("두 번째 장면 자막 텍스트")).toBeInTheDocument();
    });

    it("truncates long captions at 50 characters", () => {
      const longCaption = "이것은 매우 긴 캡션입니다 이것은 매우 긴 캡션입니다 이것은 매우 긴 캡션입니다 이것은 매우";
      const scene = buildScene({ scene_id: "s-long", start_ms: 0, scene_caption: longCaption });
      render(<PersonSceneGrid {...defaultProps} scenes={[scene]} />);
      const captionEl = screen.getByText(/이것은 매우 긴/);
      expect(captionEl.textContent!.endsWith("...")).toBe(true);
      expect(captionEl.textContent!.length).toBeLessThanOrEqual(53);
    });
  });

  describe("click behavior", () => {
    it("calls onSceneClick with start_ms when thumbnail clicked", async () => {
      const user = userEvent.setup();
      const onClick = vi.fn();
      const scenes = [buildScene({ scene_id: "s1", start_ms: 15000 })];

      render(<PersonSceneGrid {...defaultProps} scenes={scenes} onSceneClick={onClick} />);
      await user.click(screen.getByTestId("thumb-s1").closest("button")!);

      expect(onClick).toHaveBeenCalledOnce();
      expect(onClick).toHaveBeenCalledWith(15000);
    });

    it("does not crash when onSceneClick is not provided", async () => {
      const user = userEvent.setup();
      const scenes = [buildScene({ scene_id: "s1", start_ms: 0 })];

      render(<PersonSceneGrid {...defaultProps} scenes={scenes} />);
      await user.click(screen.getByTestId("thumb-s1").closest("button")!);
    });
  });

  describe("scroll container", () => {
    it("has max-height overflow constraint", () => {
      const scenes = Array.from({ length: 20 }, (_, i) =>
        buildScene({ scene_id: `s${i}`, start_ms: i * 10000 }),
      );
      const { container } = render(<PersonSceneGrid {...defaultProps} scenes={scenes} />);
      const scrollContainer = container.querySelector(".max-h-\\[340px\\]");
      expect(scrollContainer).toBeInTheDocument();
      expect(scrollContainer).toHaveClass("overflow-y-auto");
    });
  });

  describe("aspect ratio", () => {
    const scenes = [buildScene({ scene_id: "s1", start_ms: 0 })];

    it("uses 3-column grid for 16:9 aspect ratio", () => {
      const { container } = render(
        <PersonSceneGrid {...defaultProps} aspectRatio="16:9" scenes={scenes} />,
      );
      const grid = container.querySelector(".grid-cols-3");
      expect(grid).toBeInTheDocument();
    });

    it("uses 4-column grid for 9:16 aspect ratio", () => {
      const { container } = render(
        <PersonSceneGrid {...defaultProps} aspectRatio="9:16" scenes={scenes} />,
      );
      const grid = container.querySelector(".grid-cols-4");
      expect(grid).toBeInTheDocument();
    });
  });
});
