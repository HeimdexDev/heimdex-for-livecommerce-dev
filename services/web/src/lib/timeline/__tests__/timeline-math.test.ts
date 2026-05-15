import { describe, it, expect } from "vitest";
import {
  msToPixels,
  pixelsToMs,
  snapToGrid,
  formatTimelineTimestamp,
  formatVideoTimestampHMS,
} from "../timeline-math";

describe("msToPixels", () => {
  it("converts at default zoom (100 px/s)", () => {
    expect(msToPixels(1000, 100)).toBe(100);
  });

  it("scales with zoom", () => {
    expect(msToPixels(1000, 200)).toBe(200);
    expect(msToPixels(1000, 50)).toBe(50);
  });

  it("handles zero ms", () => {
    expect(msToPixels(0, 100)).toBe(0);
  });

  it("handles fractional ms", () => {
    expect(msToPixels(500, 100)).toBe(50);
  });
});

describe("pixelsToMs", () => {
  it("inverse of msToPixels at default zoom", () => {
    expect(pixelsToMs(100, 100)).toBe(1000);
  });

  it("handles zero zoom gracefully", () => {
    expect(pixelsToMs(100, 0)).toBe(0);
  });

  it("scales with zoom", () => {
    expect(pixelsToMs(200, 200)).toBe(1000);
    expect(pixelsToMs(50, 50)).toBe(1000);
  });
});

describe("snapToGrid", () => {
  it("snaps to nearest grid point", () => {
    expect(snapToGrid(1200, 1000)).toBe(1000);
    expect(snapToGrid(1600, 1000)).toBe(2000);
  });

  it("exact grid point stays unchanged", () => {
    expect(snapToGrid(2000, 1000)).toBe(2000);
  });

  it("handles zero grid gracefully", () => {
    expect(snapToGrid(1500, 0)).toBe(1500);
  });

  it("handles negative grid gracefully", () => {
    expect(snapToGrid(1500, -100)).toBe(1500);
  });
});

describe("formatTimelineTimestamp", () => {
  it("formats seconds only", () => {
    expect(formatTimelineTimestamp(5000)).toBe("0:05");
  });

  it("formats minutes and seconds", () => {
    expect(formatTimelineTimestamp(65000)).toBe("1:05");
  });

  it("formats hours", () => {
    expect(formatTimelineTimestamp(3661000)).toBe("1:01:01");
  });

  it("formats zero", () => {
    expect(formatTimelineTimestamp(0)).toBe("0:00");
  });

  it("pads seconds to two digits", () => {
    expect(formatTimelineTimestamp(3000)).toBe("0:03");
  });
});

describe("formatVideoTimestampHMS", () => {
  it("always renders HH:MM:SS, even when h=0", () => {
    expect(formatVideoTimestampHMS(0)).toBe("00:00:00");
    expect(formatVideoTimestampHMS(5000)).toBe("00:00:05");
    expect(formatVideoTimestampHMS(155_000)).toBe("00:02:35"); // 2:35 in shorts
    expect(formatVideoTimestampHMS(940_000)).toBe("00:15:40"); // 15:40
  });

  it("includes hours when ms ≥ 1hr", () => {
    expect(formatVideoTimestampHMS(3_600_000)).toBe("01:00:00");
    expect(formatVideoTimestampHMS(3_661_000)).toBe("01:01:01");
    expect(formatVideoTimestampHMS(36_000_000)).toBe("10:00:00");
  });

  it("clamps negative input to 00:00:00", () => {
    expect(formatVideoTimestampHMS(-1)).toBe("00:00:00");
    expect(formatVideoTimestampHMS(-9999)).toBe("00:00:00");
  });
});
