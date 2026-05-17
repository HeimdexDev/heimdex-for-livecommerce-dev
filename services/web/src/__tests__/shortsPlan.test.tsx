import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
// jest-dom matchers loaded via vitest.setup.ts
import { CandidateCard } from "@/features/videos/components/CandidateCard";
import { ShortsPlanPanel } from "@/features/videos/components/ShortsPlanPanel";

import { renderWithProviders } from "./test-utils";
import type { ShortsCandidateResponse } from "@/lib/types";
import { generateShortsPlan } from "@/lib/api/shorts";
import { exportToPremiere } from "@/lib/agent-export";


vi.mock("@/lib/auth", () => ({
  useAuth: () => ({
    getAccessToken: vi.fn().mockResolvedValue("test-token"),
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

vi.mock("@/lib/api/shorts", () => ({
  generateShortsPlan: vi.fn(),
}));

vi.mock("@/lib/agent-export", () => ({
  exportToPremiere: vi.fn(),
}));

const sampleCandidate: ShortsCandidateResponse = {
  candidate_id: "cand-1",
  video_id: "video-abc-123",
  scene_ids: ["scene_0", "scene_1"],
  start_ms: 5000,
  end_ms: 45000,
  title_suggestion: "Fashion Intro Segment",
  reason: "High transcript density with product mentions",
  score: 0.85,
  tags: ["fashion", "unboxing"],
  product_refs: ["product-a"],
  people_refs: ["person-1"],
  transcript_snippet: "Hello everyone, welcome to the live show.",
};

const secondCandidate: ShortsCandidateResponse = {
  ...sampleCandidate,
  candidate_id: "cand-2",
  scene_ids: ["scene_2"],
  start_ms: 46000,
  end_ms: 70000,
  title_suggestion: "Product Demo Highlight",
  score: 0.8,
  tags: ["demo"],
};

beforeEach(() => {
  vi.restoreAllMocks();
  vi.mocked(generateShortsPlan).mockReset();
  vi.mocked(exportToPremiere).mockReset();
});

describe("CandidateCard", () => {
  it("renders rank, score, title, time range", () => {
    render(
      <CandidateCard
        candidate={sampleCandidate}
        rank={1}
        isSelected={true}
        onToggle={vi.fn()}
        agentAvailable={true}
        videoId="video-abc-123"
      />,
    );

    expect(screen.getByText("#1")).toBeInTheDocument();
    expect(screen.getByText("★ 0.85")).toBeInTheDocument();
    expect(screen.getByText("Fashion Intro Segment")).toBeInTheDocument();
    expect(screen.getByText("0:05 - 0:45")).toBeInTheDocument();
  });

  it("renders tags", () => {
    render(
      <CandidateCard
        candidate={sampleCandidate}
        rank={1}
        isSelected={true}
        onToggle={vi.fn()}
        agentAvailable={true}
        videoId="video-abc-123"
      />,
    );

    expect(screen.getByText("fashion")).toBeInTheDocument();
    expect(screen.getByText("unboxing")).toBeInTheDocument();
  });

  it("renders transcript snippet", () => {
    render(
      <CandidateCard
        candidate={sampleCandidate}
        rank={1}
        isSelected={true}
        onToggle={vi.fn()}
        agentAvailable={true}
        videoId="video-abc-123"
      />,
    );

    expect(screen.getByText("Hello everyone, welcome to the live show.")).toBeInTheDocument();
  });

  it("checkbox reflects isSelected prop", () => {
    const { rerender } = render(
      <CandidateCard
        candidate={sampleCandidate}
        rank={1}
        isSelected={true}
        onToggle={vi.fn()}
        agentAvailable={true}
        videoId="video-abc-123"
      />,
    );

    expect(screen.getByRole("checkbox")).toBeChecked();

    rerender(
      <CandidateCard
        candidate={sampleCandidate}
        rank={1}
        isSelected={false}
        onToggle={vi.fn()}
        agentAvailable={true}
        videoId="video-abc-123"
      />,
    );

    expect(screen.getByRole("checkbox")).not.toBeChecked();
  });

  it("calls onToggle when checkbox clicked", async () => {
    const onToggle = vi.fn();
    const user = userEvent.setup();
    render(
      <CandidateCard
        candidate={sampleCandidate}
        rank={1}
        isSelected={false}
        onToggle={onToggle}
        agentAvailable={true}
        videoId="video-abc-123"
      />,
    );

    await user.click(screen.getByRole("checkbox"));
    expect(onToggle).toHaveBeenCalled();
  });

  it("play button enabled when agentAvailable", () => {
    render(
      <CandidateCard
        candidate={sampleCandidate}
        rank={1}
        isSelected={false}
        onToggle={vi.fn()}
        agentAvailable={true}
        videoId="video-abc-123"
      />,
    );

    expect(screen.getByRole("button", { name: "Play" })).toBeEnabled();
  });

  it("play button disabled when agent offline", () => {
    render(
      <CandidateCard
        candidate={sampleCandidate}
        rank={1}
        isSelected={false}
        onToggle={vi.fn()}
        agentAvailable={false}
        videoId="video-abc-123"
      />,
    );

    expect(screen.getByRole("button", { name: "Play" })).toBeDisabled();
  });
});

describe("ShortsPlanPanel", () => {
  it("renders Generate Shorts Plan button in idle state", () => {
    renderWithProviders(
      <ShortsPlanPanel
        videoId="video-abc-123"
        videoTitle="Spring Campaign"
        agentAvailable={true}
      />,
    );

    expect(screen.getByRole("button", { name: "Generate Shorts Plan" })).toBeInTheDocument();
  });

  it("shows Generating... when loading", async () => {
    const user = userEvent.setup();
    vi.mocked(generateShortsPlan).mockImplementation(
      () => new Promise(() => undefined),
    );

    renderWithProviders(
      <ShortsPlanPanel
        videoId="video-abc-123"
        videoTitle="Spring Campaign"
        agentAvailable={true}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Generate Shorts Plan" }));
    expect(screen.getByRole("button", { name: "Generating..." })).toBeDisabled();
  });

  it("shows error banner when plan fails", async () => {
    const user = userEvent.setup();
    vi.mocked(generateShortsPlan).mockRejectedValue(new Error("Plan failed"));

    renderWithProviders(
      <ShortsPlanPanel
        videoId="video-abc-123"
        videoTitle="Spring Campaign"
        agentAvailable={true}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Generate Shorts Plan" }));
    expect(await screen.findByText("Failed to generate shorts plan")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try Again" })).toBeInTheDocument();
  });

  it("renders candidates after successful generation", async () => {
    const user = userEvent.setup();
    vi.mocked(generateShortsPlan).mockResolvedValue({
      video_id: "video-abc-123",
      video_title: "Spring Campaign",
      total_scenes: 5,
      eligible_scenes: 3,
      candidates: [sampleCandidate, secondCandidate],
    });

    renderWithProviders(
      <ShortsPlanPanel
        videoId="video-abc-123"
        videoTitle="Spring Campaign"
        agentAvailable={true}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Generate Shorts Plan" }));
    expect(await screen.findByText("Fashion Intro Segment")).toBeInTheDocument();
    expect(screen.getByText("Product Demo Highlight")).toBeInTheDocument();
    expect(screen.getByText("2 candidates from 3 eligible scenes (5 total)")).toBeInTheDocument();
  });

  it("select all selects all candidates", async () => {
    const user = userEvent.setup();
    vi.mocked(generateShortsPlan).mockResolvedValue({
      video_id: "video-abc-123",
      video_title: "Spring Campaign",
      total_scenes: 5,
      eligible_scenes: 3,
      candidates: [sampleCandidate, secondCandidate],
    });

    renderWithProviders(
      <ShortsPlanPanel
        videoId="video-abc-123"
        videoTitle="Spring Campaign"
        agentAvailable={true}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Generate Shorts Plan" }));
    await screen.findByText("Fashion Intro Segment");

    await user.click(screen.getByRole("button", { name: "Deselect All" }));
    expect(screen.getByText("0 selected")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Select All" }));
    expect(screen.getByText("2 selected")).toBeInTheDocument();
  });

  it("export button disabled when nothing selected", async () => {
    const user = userEvent.setup();
    vi.mocked(generateShortsPlan).mockResolvedValue({
      video_id: "video-abc-123",
      video_title: "Spring Campaign",
      total_scenes: 5,
      eligible_scenes: 3,
      candidates: [sampleCandidate, secondCandidate],
    });

    renderWithProviders(
      <ShortsPlanPanel
        videoId="video-abc-123"
        videoTitle="Spring Campaign"
        agentAvailable={true}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Generate Shorts Plan" }));
    await screen.findByText("Fashion Intro Segment");
    await user.click(screen.getByRole("button", { name: "Deselect All" }));
    expect(screen.getByRole("button", { name: "Export to Premiere" })).toBeDisabled();
  });

  it("keeps candidate playback disabled when agent is offline", async () => {
    const user = userEvent.setup();
    vi.mocked(generateShortsPlan).mockResolvedValue({
      video_id: "video-abc-123",
      video_title: "Spring Campaign",
      total_scenes: 5,
      eligible_scenes: 3,
      candidates: [sampleCandidate],
    });

    renderWithProviders(
      <ShortsPlanPanel
        videoId="video-abc-123"
        videoTitle="Spring Campaign"
        agentAvailable={false}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Generate Shorts Plan" }));
    await screen.findByText("Fashion Intro Segment");
    expect(screen.getByRole("button", { name: "Export to Premiere" })).toBeEnabled();
    expect(screen.getByRole("button", { name: "Play" })).toBeDisabled();
  });
});


