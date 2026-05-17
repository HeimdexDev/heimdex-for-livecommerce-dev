import { describe, it, expect, vi } from "vitest";
import { render, fireEvent } from "@testing-library/react";
import { SceneThumbnail } from "@/components/SceneThumbnail";

vi.mock("@/lib/agent", () => ({
  getCloudThumbnailUrl: vi.fn((vid: string, sid: string) => `http://test/cloud/${vid}/${sid}`),
  getAgentThumbnailUrl: vi.fn((vid: string, sid?: string) => `http://test/agent/${vid}/${sid ?? ""}`),
}));

describe("SceneThumbnail", () => {
  it("renders cloud thumbnail URL when sceneId present", () => {
    const { container } = render(
      <SceneThumbnail videoId="vid_1" sceneId="scene_1" agentAvailable={true} />
    );
    const img = container.querySelector("img");
    expect(img).toBeTruthy();
    expect(img?.getAttribute("src")).toBe("http://test/cloud/vid_1/scene_1");
  });

  it("marks the thumbnail for lazy loading", () => {
    // Moodboard grids render 60+ thumbnails per page; lazy loading + async
    // decoding keeps initial paint cheap. Regression guard: do not drop
    // these attributes without replacing them with IntersectionObserver.
    const { container } = render(
      <SceneThumbnail videoId="vid_1" sceneId="scene_1" agentAvailable={true} />
    );
    const img = container.querySelector("img");
    expect(img?.getAttribute("loading")).toBe("lazy");
    expect(img?.getAttribute("decoding")).toBe("async");
  });

  it("falls back to agent thumbnail when cloud errors and agent is available", () => {
    const { container } = render(
      <SceneThumbnail videoId="vid_1" sceneId="scene_1" agentAvailable={true} />
    );
    const img = container.querySelector("img") as HTMLImageElement;
    fireEvent.error(img);
    const after = container.querySelector("img") as HTMLImageElement;
    expect(after?.getAttribute("src")).toBe("http://test/agent/vid_1/scene_1");
  });

  it("shows VideoIcon placeholder when no sceneId and agent unavailable", () => {
    const { container } = render(
      <SceneThumbnail videoId="vid_1" agentAvailable={false} />
    );
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("svg")).toBeTruthy();
  });

  it("renders source type badge when sourceType provided", () => {
    const { container } = render(
      <SceneThumbnail videoId="vid_1" sceneId="scene_1" agentAvailable={true} sourceType="gdrive" />
    );
    const badge = container.querySelector("span");
    expect(badge?.textContent).toBe("Drive");
  });
});
