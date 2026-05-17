import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, act, fireEvent } from "@testing-library/react";
import "@testing-library/jest-dom";
import { ScenePreviewTooltip } from "@/components/ScenePreviewTooltip";

describe("ScenePreviewTooltip", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders children", () => {
    render(
      <ScenePreviewTooltip videoId="v1" sceneId="s1">
        <span>Face</span>
      </ScenePreviewTooltip>,
    );
    expect(screen.getByText("Face")).toBeInTheDocument();
  });

  it("does not show tooltip initially", () => {
    render(
      <ScenePreviewTooltip videoId="v1" sceneId="s1" label="Person A">
        <span>Face</span>
      </ScenePreviewTooltip>,
    );
    expect(screen.queryByText("Person A")).not.toBeInTheDocument();
  });

  it("shows tooltip after delay on mouse enter", () => {
    render(
      <ScenePreviewTooltip videoId="v1" sceneId="s1" label="Person A" delayMs={100}>
        <span>Face</span>
      </ScenePreviewTooltip>,
    );
    fireEvent.mouseEnter(screen.getByText("Face").parentElement!);
    expect(screen.queryByText("Person A")).not.toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(screen.getByText("Person A")).toBeInTheDocument();
  });

  it("hides tooltip on mouse leave", () => {
    render(
      <ScenePreviewTooltip videoId="v1" sceneId="s1" label="Person A" delayMs={50}>
        <span>Face</span>
      </ScenePreviewTooltip>,
    );
    const container = screen.getByText("Face").parentElement!;

    fireEvent.mouseEnter(container);
    act(() => {
      vi.advanceTimersByTime(50);
    });
    expect(screen.getByText("Person A")).toBeInTheDocument();

    fireEvent.mouseLeave(container);
    expect(screen.queryByText("Person A")).not.toBeInTheDocument();
  });

  it("cancels tooltip on mouse leave before delay completes", () => {
    render(
      <ScenePreviewTooltip videoId="v1" sceneId="s1" label="Person A" delayMs={200}>
        <span>Face</span>
      </ScenePreviewTooltip>,
    );
    const container = screen.getByText("Face").parentElement!;

    fireEvent.mouseEnter(container);
    act(() => {
      vi.advanceTimersByTime(100);
    });
    fireEvent.mouseLeave(container);

    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(screen.queryByText("Person A")).not.toBeInTheDocument();
  });

  it("dismisses tooltip on pointer down", () => {
    render(
      <ScenePreviewTooltip videoId="v1" sceneId="s1" label="Person A" delayMs={50}>
        <span>Face</span>
      </ScenePreviewTooltip>,
    );
    const container = screen.getByText("Face").parentElement!;

    fireEvent.mouseEnter(container);
    act(() => {
      vi.advanceTimersByTime(50);
    });
    expect(screen.getByText("Person A")).toBeInTheDocument();

    fireEvent.pointerDown(container);
    expect(screen.queryByText("Person A")).not.toBeInTheDocument();
  });

  it("does not show tooltip when disabled", () => {
    render(
      <ScenePreviewTooltip videoId="v1" sceneId="s1" label="Person A" delayMs={50} disabled>
        <span>Face</span>
      </ScenePreviewTooltip>,
    );
    const container = screen.getByText("Face").parentElement!;

    fireEvent.mouseEnter(container);
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(screen.queryByText("Person A")).not.toBeInTheDocument();
  });

  it("does not show tooltip when videoId is null", () => {
    render(
      <ScenePreviewTooltip videoId={null} sceneId="s1" label="Person A" delayMs={50}>
        <span>Face</span>
      </ScenePreviewTooltip>,
    );
    const container = screen.getByText("Face").parentElement!;

    fireEvent.mouseEnter(container);
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(screen.queryByText("Person A")).not.toBeInTheDocument();
  });

  it("does not show tooltip when sceneId is null", () => {
    render(
      <ScenePreviewTooltip videoId="v1" sceneId={null} label="Person A" delayMs={50}>
        <span>Face</span>
      </ScenePreviewTooltip>,
    );
    const container = screen.getByText("Face").parentElement!;

    fireEvent.mouseEnter(container);
    act(() => {
      vi.advanceTimersByTime(100);
    });
    expect(screen.queryByText("Person A")).not.toBeInTheDocument();
  });

  it("renders badge when provided", () => {
    render(
      <ScenePreviewTooltip videoId="v1" sceneId="s1" label="Person A" badge="5개 장면" delayMs={50}>
        <span>Face</span>
      </ScenePreviewTooltip>,
    );
    const container = screen.getByText("Face").parentElement!;

    fireEvent.mouseEnter(container);
    act(() => {
      vi.advanceTimersByTime(50);
    });
    expect(screen.getByText("5개 장면")).toBeInTheDocument();
  });

  it("renders thumbnail img with correct src", () => {
    render(
      <ScenePreviewTooltip videoId="vid-1" sceneId="scene-1" label="Test" delayMs={50}>
        <span>Face</span>
      </ScenePreviewTooltip>,
    );
    const container = screen.getByText("Face").parentElement!;

    fireEvent.mouseEnter(container);
    act(() => {
      vi.advanceTimersByTime(50);
    });
    const img = screen.getByAltText("Test");
    expect(img).toHaveAttribute("src", "/api/thumbnails/vid-1/scene-1");
  });

  it("hides tooltip when image errors", () => {
    render(
      <ScenePreviewTooltip videoId="v1" sceneId="s1" label="Person A" delayMs={50}>
        <span>Face</span>
      </ScenePreviewTooltip>,
    );
    const container = screen.getByText("Face").parentElement!;

    fireEvent.mouseEnter(container);
    act(() => {
      vi.advanceTimersByTime(50);
    });
    const img = screen.getByRole("img");
    fireEvent.error(img);

    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("uses default delay of 200ms", () => {
    render(
      <ScenePreviewTooltip videoId="v1" sceneId="s1" label="Person A">
        <span>Face</span>
      </ScenePreviewTooltip>,
    );
    const container = screen.getByText("Face").parentElement!;

    fireEvent.mouseEnter(container);
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(screen.queryByText("Person A")).not.toBeInTheDocument();

    act(() => {
      vi.advanceTimersByTime(50);
    });
    expect(screen.getByText("Person A")).toBeInTheDocument();
  });

  it("re-shows tooltip on re-hover after dismiss", () => {
    render(
      <ScenePreviewTooltip videoId="v1" sceneId="s1" label="Person A" delayMs={50}>
        <span>Face</span>
      </ScenePreviewTooltip>,
    );
    const container = screen.getByText("Face").parentElement!;

    fireEvent.mouseEnter(container);
    act(() => {
      vi.advanceTimersByTime(50);
    });
    expect(screen.getByText("Person A")).toBeInTheDocument();

    fireEvent.mouseLeave(container);
    expect(screen.queryByText("Person A")).not.toBeInTheDocument();

    fireEvent.mouseEnter(container);
    act(() => {
      vi.advanceTimersByTime(50);
    });
    expect(screen.getByText("Person A")).toBeInTheDocument();
  });
});
