import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

import {
  VideoSegmentRangeSlider,
  snapToNearest,
} from "../components/VideoSegmentRangeSlider";

const ONE_MIN = 60_000;
const FIVE_MIN = 300_000;

describe("VideoSegmentRangeSlider", () => {
  it("renders nothing when durationMs is 0", () => {
    const { container } = render(
      <VideoSegmentRangeSlider
        durationMs={0}
        startMs={null}
        endMs={null}
        onChange={vi.fn()}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("displays both handles with timestamps at extremes when start/end are null", () => {
    render(
      <VideoSegmentRangeSlider
        durationMs={FIVE_MIN}
        startMs={null}
        endMs={null}
        onChange={vi.fn()}
      />,
    );
    expect(screen.getByTestId("range-handle-start")).toBeInTheDocument();
    expect(screen.getByTestId("range-handle-end")).toBeInTheDocument();
    // Whole-video display: formatVideoTimestampHMS always renders HH:MM:SS
    expect(screen.getByTestId("range-label-start").textContent).toBe("00:00:00");
    expect(screen.getByTestId("range-label-end").textContent).toBe("00:05:00");
  });

  it("nudges start handle right by 1s on ArrowRight", () => {
    const onChange = vi.fn();
    render(
      <VideoSegmentRangeSlider
        durationMs={FIVE_MIN}
        startMs={ONE_MIN}
        endMs={FIVE_MIN}
        onChange={onChange}
      />,
    );
    fireEvent.keyDown(screen.getByTestId("range-handle-start"), {
      key: "ArrowRight",
    });
    expect(onChange).toHaveBeenCalledWith({
      startMs: ONE_MIN + 1_000,
      endMs: FIVE_MIN,
    });
  });

  it("nudges end handle by 10s on Shift+ArrowLeft", () => {
    const onChange = vi.fn();
    render(
      <VideoSegmentRangeSlider
        durationMs={FIVE_MIN}
        startMs={ONE_MIN}
        endMs={FIVE_MIN}
        onChange={onChange}
      />,
    );
    fireEvent.keyDown(screen.getByTestId("range-handle-end"), {
      key: "ArrowLeft",
      shiftKey: true,
    });
    expect(onChange).toHaveBeenCalledWith({
      startMs: ONE_MIN,
      endMs: FIVE_MIN - 10_000,
    });
  });

  it("enforces min 1s separation: start cannot equal or pass end", () => {
    const onChange = vi.fn();
    render(
      <VideoSegmentRangeSlider
        durationMs={FIVE_MIN}
        startMs={FIVE_MIN - 500}
        endMs={FIVE_MIN}
        onChange={onChange}
      />,
    );
    fireEvent.keyDown(screen.getByTestId("range-handle-start"), {
      key: "ArrowRight",
    });
    // Ceiling = endMs - 1s = 299_000; clamped from 300_500 → can't exceed
    expect(onChange).toHaveBeenCalledWith({
      startMs: FIVE_MIN - 1_000,
      endMs: FIVE_MIN,
    });
  });

  it("clamps end handle at duration", () => {
    const onChange = vi.fn();
    render(
      <VideoSegmentRangeSlider
        durationMs={FIVE_MIN}
        startMs={0}
        endMs={FIVE_MIN}
        onChange={onChange}
      />,
    );
    fireEvent.keyDown(screen.getByTestId("range-handle-end"), {
      key: "ArrowRight",
    });
    expect(onChange).toHaveBeenCalledWith({ startMs: 0, endMs: FIVE_MIN });
  });

  it("clamps start handle at 0", () => {
    const onChange = vi.fn();
    render(
      <VideoSegmentRangeSlider
        durationMs={FIVE_MIN}
        startMs={0}
        endMs={FIVE_MIN}
        onChange={onChange}
      />,
    );
    fireEvent.keyDown(screen.getByTestId("range-handle-start"), {
      key: "ArrowLeft",
    });
    expect(onChange).toHaveBeenCalledWith({ startMs: 0, endMs: FIVE_MIN });
  });

  it("disabled keyboard nudge is a no-op", () => {
    const onChange = vi.fn();
    render(
      <VideoSegmentRangeSlider
        durationMs={FIVE_MIN}
        startMs={ONE_MIN}
        endMs={FIVE_MIN}
        onChange={onChange}
        disabled
      />,
    );
    fireEvent.keyDown(screen.getByTestId("range-handle-start"), {
      key: "ArrowRight",
    });
    expect(onChange).not.toHaveBeenCalled();
  });

  it("preserves null on the side that wasn't moved", () => {
    const onChange = vi.fn();
    render(
      <VideoSegmentRangeSlider
        durationMs={FIVE_MIN}
        startMs={null}
        endMs={null}
        onChange={onChange}
      />,
    );
    fireEvent.keyDown(screen.getByTestId("range-handle-start"), {
      key: "ArrowRight",
    });
    // start moves to 1_000; end stays null (caller decides whether to
    // synthesize a value at submit time)
    expect(onChange).toHaveBeenCalledWith({ startMs: 1_000, endMs: null });
  });
});

describe("snapToNearest (D4)", () => {
  it("returns ms unchanged when targets is empty", () => {
    expect(snapToNearest(12_345, [], 500)).toBe(12_345);
  });

  it("returns ms unchanged when radius is 0", () => {
    expect(snapToNearest(12_345, [12_000, 13_000], 0)).toBe(12_345);
  });

  it("snaps to nearest target within radius", () => {
    expect(snapToNearest(12_300, [10_000, 12_000, 14_000], 500)).toBe(12_000);
    expect(snapToNearest(13_900, [10_000, 12_000, 14_000], 500)).toBe(14_000);
  });

  it("does NOT snap when nearest target is outside radius", () => {
    expect(snapToNearest(12_700, [10_000, 12_000, 14_000], 500)).toBe(12_700);
  });

  it("ties prefer the first target encountered", () => {
    // Both 11_500 and 12_500 are equidistant from 12_000; iteration is
    // ordered, so the first one (11_500 if listed first) wins.
    expect(snapToNearest(12_000, [11_500, 12_500], 1_000)).toBe(11_500);
  });
});

describe("VideoSegmentRangeSlider — D4 snap behavior", () => {
  const ONE_MIN = 60_000;
  const FIVE_MIN = 300_000;

  it("renders snap-target ticks for interior boundaries", () => {
    render(
      <VideoSegmentRangeSlider
        durationMs={FIVE_MIN}
        startMs={null}
        endMs={null}
        onChange={vi.fn()}
        snapTargetsMs={[0, 60_000, 120_000, 180_000, 240_000, FIVE_MIN]}
      />,
    );
    // Ticks render only for interior boundaries (exclude 0 and durationMs).
    expect(screen.getAllByTestId("range-snap-tick")).toHaveLength(4);
  });

  it("renders no ticks when snapTargetsMs is undefined", () => {
    render(
      <VideoSegmentRangeSlider
        durationMs={FIVE_MIN}
        startMs={null}
        endMs={null}
        onChange={vi.fn()}
      />,
    );
    expect(screen.queryAllByTestId("range-snap-tick")).toHaveLength(0);
  });

  it("ArrowRight from a value just below a snap target lands ON the target", () => {
    const onChange = vi.fn();
    // Start at 59_500ms; ArrowRight = +1000ms = 60_500ms; nearest target
    // 60_000ms is within default 500ms radius → snaps to 60_000ms.
    render(
      <VideoSegmentRangeSlider
        durationMs={FIVE_MIN}
        startMs={59_500}
        endMs={FIVE_MIN}
        onChange={onChange}
        snapTargetsMs={[60_000, 120_000]}
      />,
    );
    fireEvent.keyDown(screen.getByTestId("range-handle-start"), {
      key: "ArrowRight",
    });
    expect(onChange).toHaveBeenCalledWith({
      startMs: 60_000,
      endMs: FIVE_MIN,
    });
  });

  it("does NOT snap when the nearest target is outside the radius", () => {
    const onChange = vi.fn();
    render(
      <VideoSegmentRangeSlider
        durationMs={FIVE_MIN}
        startMs={ONE_MIN}
        endMs={FIVE_MIN}
        onChange={onChange}
        snapTargetsMs={[120_000]}
        snapRadiusMs={500}
      />,
    );
    // ArrowRight = +1s = 61_000; far from 120_000; no snap.
    fireEvent.keyDown(screen.getByTestId("range-handle-start"), {
      key: "ArrowRight",
    });
    expect(onChange).toHaveBeenCalledWith({
      startMs: 61_000,
      endMs: FIVE_MIN,
    });
  });
});
