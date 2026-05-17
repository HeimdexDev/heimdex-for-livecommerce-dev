import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { AvatarThumbnail } from "@/components/people/AvatarThumbnail";
import type { PersonResponse } from "@/lib/types";

vi.mock("@/lib/agent", () => ({
  getFaceThumbnailUrl: vi.fn((id: string) => `http://test/face/${id}`),
  getCloudThumbnailUrl: vi.fn((vid: string, sid: string) => `http://test/scene/${vid}/${sid}`),
}));

const basePerson: PersonResponse = {
  person_cluster_id: "cluster_1",
  label: "Test Person",
  face_count: 5,
  is_excluded: false,
  last_seen_scene_time: null,
  representative_video_id: "vid_1",
  representative_scene_id: "scene_1",
  matched_video_titles: [],
};

describe("AvatarThumbnail", () => {
  it("renders face thumbnail URL", () => {
    const { container } = render(
      <AvatarThumbnail person={basePerson} agentAvailable={true} />
    );
    const img = container.querySelector("img");
    expect(img).toBeTruthy();
    expect(img?.getAttribute("src")).toBe("http://test/face/cluster_1");
  });

  it("falls back to scene thumbnail on face error", () => {
    const { container } = render(
      <AvatarThumbnail person={basePerson} agentAvailable={true} />
    );
    const img = container.querySelector("img") as HTMLImageElement;
    expect(img).toBeTruthy();
    // Simulate image error
    fireEvent.error(img);
    // After error, should try scene thumbnail
    const newImg = container.querySelector("img") as HTMLImageElement;
    expect(newImg?.getAttribute("src")).toBe("http://test/scene/vid_1/scene_1");
  });

  it("shows PersonIcon fallback when both thumbnails fail to load", () => {
    const { container } = render(
      <AvatarThumbnail person={basePerson} agentAvailable={true} />
    );
    const img = container.querySelector("img") as HTMLImageElement;
    expect(img).toBeTruthy();
    fireEvent.error(img);
    fireEvent.error(img);
    const fallbackDiv = container.querySelector(".relative.flex");
    expect(fallbackDiv).toBeTruthy();
  });
});
