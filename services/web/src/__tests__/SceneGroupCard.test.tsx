import { describe, expect, it, vi } from "vitest";
import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import "@testing-library/jest-dom";
import { SceneGroupCard } from "@/features/videos/components/SceneGroupCard";
import { renderWithProviders } from "./test-utils";
import type { SceneGroup, VideoScene } from "@/lib/types";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), back: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ getAccessToken: vi.fn().mockResolvedValue("token") }),
}));

vi.mock("@/features/search/hooks/useAgent", () => ({
  useAgent: () => ({ isAvailable: false }),
}));

vi.mock("@/lib/orgSettings", () => ({
  useOrgSettings: () => ({
    settings: { thumbnail_aspect_ratio: "16:9" },
  }),
  OrgSettingsProvider: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/SceneThumbnail", () => ({
  SceneThumbnail: ({ sceneId }: { sceneId?: string }) => (
    <div data-testid={`thumb-${sceneId}`}>thumb</div>
  ),
}));

function makeScene(id: string, startMs: number, endMs: number): VideoScene {
  return {
    scene_id: id,
    start_ms: startMs,
    end_ms: endMs,
    transcript_raw: "",
    transcript_char_count: 0,
    keyword_tags: [],
    product_tags: [],
    product_entities: [],
    speech_segment_count: 0,
    people_cluster_ids: [],
    ingest_time: null,
    keyframe_timestamp_ms: startMs,
  };
}

function makeGroup(sceneCount: number): SceneGroup {
  const scenes = Array.from({ length: sceneCount }, (_, i) =>
    makeScene(`s${i}`, i * 10000, (i + 1) * 10000),
  );
  return {
    group_index: 0,
    start_ms: 0,
    end_ms: sceneCount * 10000,
    scene_count: sceneCount,
    representative_scene_id: scenes[Math.floor(sceneCount / 2)].scene_id,
    scenes,
  };
}

describe("SceneGroupCard", () => {
  it("renders collapsed state with time range and scene count", () => {
    const group = makeGroup(3);
    renderWithProviders(
      <SceneGroupCard
        group={group}
        videoId="v1"
        agentAvailable={false}
        aspectRatio="16:9"
      />,
    );

    expect(screen.getByText("3개 장면")).toBeInTheDocument();
    expect(screen.getByTestId("thumb-s1")).toBeInTheDocument();
  });

  it("does not show scene cards when collapsed", () => {
    const group = makeGroup(3);
    renderWithProviders(
      <SceneGroupCard
        group={group}
        videoId="v1"
        agentAvailable={false}
        aspectRatio="16:9"
      />,
    );

    expect(screen.queryByText("00:00:00")).toBeNull();
  });

  it("expands on click to show individual scene cards", async () => {
    const group = makeGroup(3);
    const user = userEvent.setup();

    renderWithProviders(
      <SceneGroupCard
        group={group}
        videoId="v1"
        agentAvailable={false}
        aspectRatio="16:9"
      />,
    );

    const toggleButton = screen.getByRole("button");
    await user.click(toggleButton);

    expect(screen.getAllByTestId(/^thumb-s\d$/).length).toBe(4);
  });

  it("collapses on second click", async () => {
    const group = makeGroup(2);
    const user = userEvent.setup();

    renderWithProviders(
      <SceneGroupCard
        group={group}
        videoId="v1"
        agentAvailable={false}
        aspectRatio="16:9"
      />,
    );

    const toggleButton = screen.getByRole("button");
    await user.click(toggleButton);
    expect(screen.getAllByTestId(/^thumb-s\d$/).length).toBeGreaterThan(1);

    await user.click(toggleButton);
    expect(screen.getAllByTestId(/^thumb-s\d$/).length).toBe(1);
  });

  it("renders scene count badge correctly for large groups", () => {
    const group = makeGroup(15);
    renderWithProviders(
      <SceneGroupCard
        group={group}
        videoId="v1"
        agentAvailable={false}
        aspectRatio="16:9"
      />,
    );

    expect(screen.getByText("15개 장면")).toBeInTheDocument();
  });
});
