import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { ModeTabs } from "../components/ModeTabs";

// Same trick as PersonSelect.test — useVideoPeople ends up using
// useAuth, and the mock must define a stable getAccessToken inside
// the factory or the videoId-keyed effect re-fires every render →
// worker OOM. Lesson logged in the plan.
vi.mock("@/lib/auth", () => {
  const stableGetAccessToken = async () => "tok";
  return {
    useAuth: () => ({ getAccessToken: stableGetAccessToken }),
  };
});

vi.mock("@/lib/api/videos", () => ({
  getVideoPeople: vi.fn().mockResolvedValue({
    video_id: "vid",
    people: [
      { person_cluster_id: "p1", label: "호스트", face_count: 10 },
    ],
    total: 1,
  }),
}));

vi.mock("@/lib/agent", () => ({
  getFaceThumbnailUrl: (id: string) => `/face/${id}`,
}));

vi.mock("@/components/icons", () => ({
  PersonIcon: () => <svg data-testid="person-icon" />,
}));

beforeEach(() => {
  vi.clearAllMocks();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("ModeTabs", () => {
  it("renders three tabs with the active one selected", () => {
    render(
      <ModeTabs
        videoId="vid"
        mode="both"
        personClusterId={null}
        isLoading={false}
        onModeChange={() => {}}
        onPersonChange={() => {}}
      />,
    );
    const both = screen.getByRole("tab", { name: "혼합" });
    const human = screen.getByRole("tab", { name: "인물 중심" });
    const product = screen.getByRole("tab", { name: "상품 중심" });
    expect(both).toHaveAttribute("aria-selected", "true");
    expect(human).toHaveAttribute("aria-selected", "false");
    expect(product).toHaveAttribute("aria-selected", "false");
  });

  it("invokes onModeChange when a tab is clicked", () => {
    const onModeChange = vi.fn();
    render(
      <ModeTabs
        videoId="vid"
        mode="both"
        personClusterId={null}
        isLoading={false}
        onModeChange={onModeChange}
        onPersonChange={() => {}}
      />,
    );
    fireEvent.click(screen.getByRole("tab", { name: "상품 중심" }));
    expect(onModeChange).toHaveBeenCalledWith("product");
  });

  it("does not show the inline person picker when mode is not human", () => {
    render(
      <ModeTabs
        videoId="vid"
        mode="both"
        personClusterId={null}
        isLoading={false}
        onModeChange={() => {}}
        onPersonChange={() => {}}
      />,
    );
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
  });

  it("shows the inline person picker when mode is human", async () => {
    render(
      <ModeTabs
        videoId="vid"
        mode="human"
        personClusterId={null}
        isLoading={false}
        onModeChange={() => {}}
        onPersonChange={() => {}}
      />,
    );
    expect(screen.getByRole("combobox")).toBeInTheDocument();
    expect(
      screen.getByText(/인물을 선택하면 해당 인물이 등장하는/),
    ).toBeInTheDocument();
  });

  it("hides the prompt copy once a person is selected (no longer blocking)", () => {
    render(
      <ModeTabs
        videoId="vid"
        mode="human"
        personClusterId="p1"
        isLoading={false}
        onModeChange={() => {}}
        onPersonChange={() => {}}
      />,
    );
    expect(screen.getByRole("combobox")).toBeInTheDocument();
    expect(
      screen.queryByText(/인물을 선택하면 해당 인물이 등장하는/),
    ).not.toBeInTheDocument();
  });

  it("disables tabs while loading so users can't double-fire", () => {
    render(
      <ModeTabs
        videoId="vid"
        mode="both"
        personClusterId={null}
        isLoading={true}
        onModeChange={() => {}}
        onPersonChange={() => {}}
      />,
    );
    const both = screen.getByRole("tab", { name: "혼합" });
    const human = screen.getByRole("tab", { name: "인물 중심" });
    expect(both).toBeDisabled();
    expect(human).toBeDisabled();
  });

  it("propagates onPersonChange when the picker fires", async () => {
    const onPersonChange = vi.fn();
    render(
      <ModeTabs
        videoId="vid"
        mode="human"
        personClusterId={null}
        isLoading={false}
        onModeChange={() => {}}
        onPersonChange={onPersonChange}
      />,
    );
    fireEvent.click(screen.getByRole("combobox"));
    await waitFor(() => expect(screen.getByText("호스트")).toBeInTheDocument());
    fireEvent.click(screen.getByText("호스트"));
    expect(onPersonChange).toHaveBeenCalledWith("p1");
  });
});
