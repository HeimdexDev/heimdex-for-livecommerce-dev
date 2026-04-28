import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import { CandidateCard } from "../components/CandidateCard";
import type { AutoClipResponse } from "@/lib/types";
import type { CandidateState } from "../hooks/useCandidateRenderJobs";

vi.mock("@/components/SceneThumbnail", () => ({
  SceneThumbnail: () => <div data-testid="thumb" />,
}));

const baseClip: AutoClipResponse = {
  scene_ids: ["vid_scene_000", "vid_scene_001"],
  members: [
    { scene_id: "vid_scene_000", start_ms: 0, end_ms: 15_000, score: 0.8 },
    { scene_id: "vid_scene_001", start_ms: 30_000, end_ms: 45_000, score: 0.7 },
  ],
  start_ms: 0,
  end_ms: 45_000,
  duration_ms: 30_000,
  score: 0.75,
  reasons: [],
  is_continuous: false,
};

function renderCard(stateOverride?: Partial<{ state: CandidateState; isSelected: boolean }>) {
  const onSelect = vi.fn();
  const onDownload = vi.fn();
  const onDelete = vi.fn();
  render(
    <CandidateCard
      index={0}
      clip={baseClip}
      videoId="vid"
      isSelected={stateOverride?.isSelected ?? false}
      state={stateOverride?.state ?? { kind: "candidate" }}
      onSelect={onSelect}
      onDownload={onDownload}
      onDelete={onDelete}
      editorHref="/edit"
    />,
  );
  return { onSelect, onDownload, onDelete };
}

describe("CandidateCard", () => {
  it("renders candidate state with edit + download + delete affordances", () => {
    renderCard();
    expect(screen.getByText("클립 1")).toBeInTheDocument();
    expect(screen.getByLabelText("클립 1 편집")).toBeInTheDocument();
    expect(screen.getByLabelText("클립 1 렌더링 후 다운로드")).toBeInTheDocument();
    expect(screen.getByLabelText("클립 1 삭제")).toBeInTheDocument();
  });

  it("shows pill state for queued/rendering/completed/failed", () => {
    const { rerender } = render(
      <CandidateCard
        index={0}
        clip={baseClip}
        videoId="vid"
        isSelected={false}
        state={{
          kind: "queued",
          job: {
            id: "j1",
            video_id: "vid",
            title: null,
            status: "queued",
            created_at: "",
            completed_at: null,
            render_time_ms: null,
            output_duration_ms: null,
            output_size_bytes: null,
            error: null,
            download_url: null,
            thumbnail_video_id: null,
            thumbnail_scene_id: null,
          },
        }}
        onSelect={() => {}}
        onDownload={() => {}}
        onDelete={() => {}}
        editorHref="/edit"
      />,
    );
    expect(screen.getByText("대기 중")).toBeInTheDocument();

    rerender(
      <CandidateCard
        index={0}
        clip={baseClip}
        videoId="vid"
        isSelected={false}
        state={{
          kind: "completed",
          job: {
            id: "j1",
            video_id: "vid",
            title: null,
            status: "completed",
            created_at: "",
            completed_at: "",
            render_time_ms: 1000,
            output_duration_ms: 30_000,
            output_size_bytes: 1024,
            error: null,
            download_url: "/dl",
            thumbnail_video_id: "vid",
            thumbnail_scene_id: "vid_scene_000",
          },
        }}
        onSelect={() => {}}
        onDownload={() => {}}
        onDelete={() => {}}
        editorHref="/edit"
      />,
    );
    expect(screen.getByText("완료")).toBeInTheDocument();
    // Edit link is hidden in completed state — user is past the
    // "preview" stage, the card is now a render-job artifact.
    expect(screen.queryByLabelText("클립 1 편집")).not.toBeInTheDocument();
  });

  it("shows error message in failed state", () => {
    render(
      <CandidateCard
        index={0}
        clip={baseClip}
        videoId="vid"
        isSelected={false}
        state={{ kind: "failed", job: null, error: "render worker timed out" }}
        onSelect={() => {}}
        onDownload={() => {}}
        onDelete={() => {}}
        editorHref="/edit"
      />,
    );
    expect(screen.getByText("실패")).toBeInTheDocument();
    expect(screen.getByText("render worker timed out")).toBeInTheDocument();
  });

  it("invokes onDownload when the user clicks the download button", () => {
    const { onDownload } = renderCard();
    fireEvent.click(screen.getByLabelText("클립 1 렌더링 후 다운로드"));
    expect(onDownload).toHaveBeenCalledTimes(1);
  });

  it("invokes onDelete and stops propagation so the card isn't selected", () => {
    const { onSelect, onDelete } = renderCard();
    fireEvent.click(screen.getByLabelText("클립 1 삭제"));
    expect(onDelete).toHaveBeenCalledTimes(1);
    expect(onSelect).not.toHaveBeenCalled();
  });

  it("invokes onSelect when the card body is clicked", () => {
    const { onSelect } = renderCard();
    // Click the article container (not a button)
    const article = screen.getByLabelText("자동 선택 클립 1");
    fireEvent.click(article);
    expect(onSelect).toHaveBeenCalled();
  });

  it("highlights when isSelected=true", () => {
    renderCard({ isSelected: true });
    expect(screen.getByLabelText("자동 선택 클립 1")).toHaveAttribute("aria-selected", "true");
  });
});
