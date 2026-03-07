import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { TimelineBar } from "@/features/people/components/TimelineBar";
import type { PersonTimelineScene } from "@/lib/types/people";

const SCENES: PersonTimelineScene[] = [
  { scene_id: "v1_scene_0", start_ms: 0, end_ms: 5000, has_person: true },
  { scene_id: "v1_scene_1", start_ms: 5000, end_ms: 10000, has_person: false },
  { scene_id: "v1_scene_2", start_ms: 10000, end_ms: 15000, has_person: true },
  { scene_id: "v1_scene_3", start_ms: 15000, end_ms: 20000, has_person: false },
  { scene_id: "v1_scene_4", start_ms: 20000, end_ms: 25000, has_person: true },
];

describe("TimelineBar", () => {
  const mockOnSceneClick = vi.fn();

  beforeEach(() => {
    vi.useFakeTimers();
    mockOnSceneClick.mockReset();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders correct number of segments", () => {
    const { container } = render(
      <TimelineBar
        scenes={SCENES}
        videoId="vid1"
        videoTitle="Test Video"
        onSceneClick={mockOnSceneClick}
      />,
    );
    const bar = container.querySelector("[role='group']")!;
    const segments = bar.querySelectorAll(":scope > div:not(.absolute)");
    expect(segments.length).toBe(5);
  });

  it("applies blue class for present and gray for absent", () => {
    const { container } = render(
      <TimelineBar
        scenes={SCENES}
        videoId="vid1"
        videoTitle="Test Video"
        onSceneClick={mockOnSceneClick}
      />,
    );
    const bar = container.querySelector("[role='group']")!;
    const segments = bar.querySelectorAll(":scope > div:not(.absolute)");

    expect(segments[0].className).toContain("bg-blue-500");
    expect(segments[1].className).toContain("bg-gray-200");
    expect(segments[2].className).toContain("bg-blue-500");
    expect(segments[3].className).toContain("bg-gray-200");
    expect(segments[4].className).toContain("bg-blue-500");
  });

  it("calls onSceneClick with correct videoId and startMs", () => {
    const { container } = render(
      <TimelineBar
        scenes={SCENES}
        videoId="vid1"
        videoTitle="Test Video"
        onSceneClick={mockOnSceneClick}
      />,
    );
    const bar = container.querySelector("[role='group']")!;
    const segments = bar.querySelectorAll(":scope > div:not(.absolute)");

    fireEvent.click(segments[0]);
    expect(mockOnSceneClick).toHaveBeenCalledWith("vid1", 0);

    fireEvent.click(segments[2]);
    expect(mockOnSceneClick).toHaveBeenCalledWith("vid1", 10000);

    fireEvent.click(segments[4]);
    expect(mockOnSceneClick).toHaveBeenCalledWith("vid1", 20000);
  });

  it("does not show tooltip initially", () => {
    render(
      <TimelineBar
        scenes={SCENES}
        videoId="vid1"
        videoTitle="Test Video"
        onSceneClick={mockOnSceneClick}
      />,
    );
    expect(screen.queryByText(/장면/)).not.toBeInTheDocument();
  });

  it("shows tooltip after 150ms delay on hover", () => {
    const { container } = render(
      <TimelineBar
        scenes={SCENES}
        videoId="vid1"
        videoTitle="Test Video"
        onSceneClick={mockOnSceneClick}
      />,
    );
    const bar = container.querySelector("[role='group']")!;
    const segments = bar.querySelectorAll(":scope > div:not(.absolute)");

    fireEvent.mouseEnter(segments[2]);
    expect(screen.queryByText(/장면 3/)).not.toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(screen.getByText(/장면 3/)).toBeInTheDocument();
  });

  it("hides tooltip on mouse leave", () => {
    const { container } = render(
      <TimelineBar
        scenes={SCENES}
        videoId="vid1"
        videoTitle="Test Video"
        onSceneClick={mockOnSceneClick}
      />,
    );
    const bar = container.querySelector("[role='group']")!;
    const segments = bar.querySelectorAll(":scope > div:not(.absolute)");

    fireEvent.mouseEnter(segments[0]);
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(screen.getByText(/장면 1/)).toBeInTheDocument();

    fireEvent.mouseLeave(segments[0]);
    expect(screen.queryByText(/장면 1/)).not.toBeInTheDocument();
  });

  it("cancels tooltip when mouse leaves before delay", () => {
    const { container } = render(
      <TimelineBar
        scenes={SCENES}
        videoId="vid1"
        videoTitle="Test Video"
        onSceneClick={mockOnSceneClick}
      />,
    );
    const bar = container.querySelector("[role='group']")!;
    const segments = bar.querySelectorAll(":scope > div:not(.absolute)");

    fireEvent.mouseEnter(segments[0]);
    act(() => {
      vi.advanceTimersByTime(50);
    });
    fireEvent.mouseLeave(segments[0]);

    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(screen.queryByText(/장면/)).not.toBeInTheDocument();
  });

  it("shows correct timestamp in tooltip label", () => {
    const { container } = render(
      <TimelineBar
        scenes={SCENES}
        videoId="vid1"
        videoTitle="Test Video"
        onSceneClick={mockOnSceneClick}
      />,
    );
    const bar = container.querySelector("[role='group']")!;
    const segments = bar.querySelectorAll(":scope > div:not(.absolute)");

    fireEvent.mouseEnter(segments[4]);
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(screen.getByText("장면 5 · 0:20")).toBeInTheDocument();
  });

  it("renders thumbnail img with correct src", () => {
    const { container } = render(
      <TimelineBar
        scenes={SCENES}
        videoId="vid1"
        videoTitle="Test Video"
        onSceneClick={mockOnSceneClick}
      />,
    );
    const bar = container.querySelector("[role='group']")!;
    const segments = bar.querySelectorAll(":scope > div:not(.absolute)");

    fireEvent.mouseEnter(segments[0]);
    act(() => {
      vi.advanceTimersByTime(150);
    });
    const img = screen.getByRole("img");
    expect(img).toHaveAttribute("src", "/api/thumbnails/vid1/v1_scene_0");
  });

  it("hides tooltip when image errors", () => {
    const { container } = render(
      <TimelineBar
        scenes={SCENES}
        videoId="vid1"
        videoTitle="Test Video"
        onSceneClick={mockOnSceneClick}
      />,
    );
    const bar = container.querySelector("[role='group']")!;
    const segments = bar.querySelectorAll(":scope > div:not(.absolute)");

    fireEvent.mouseEnter(segments[0]);
    act(() => {
      vi.advanceTimersByTime(150);
    });
    const img = screen.getByRole("img");
    fireEvent.error(img);

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("renders aria-label with video title", () => {
    const { container } = render(
      <TimelineBar
        scenes={SCENES}
        videoId="vid1"
        videoTitle="Test Video"
        onSceneClick={mockOnSceneClick}
      />,
    );
    const bar = container.querySelector("[role='group']")!;
    expect(bar).toHaveAttribute("aria-label", "Test Video 타임라인");
  });

  it("renders fallback aria-label when title is null", () => {
    const { container } = render(
      <TimelineBar
        scenes={SCENES}
        videoId="vid1"
        videoTitle={null}
        onSceneClick={mockOnSceneClick}
      />,
    );
    const bar = container.querySelector("[role='group']")!;
    expect(bar).toHaveAttribute("aria-label", "타임라인");
  });

  it("renders nothing when scenes is empty", () => {
    const { container } = render(
      <TimelineBar
        scenes={[]}
        videoId="vid1"
        videoTitle="Test"
        onSceneClick={mockOnSceneClick}
      />,
    );
    const bar = container.querySelector("[role='group']")!;
    const segments = bar.querySelectorAll(":scope > div:not(.absolute)");
    expect(segments.length).toBe(0);
  });
});
