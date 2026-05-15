import { describe, it, expect } from "vitest";

interface Detection {
  frame_idx: number;
  t_ms: number;
  category: string;
  label: string;
  confidence: number;
  bbox_norm: [number, number, number, number];
  from_cache: boolean;
}

function groupByCategory(detections: Detection[]): Record<string, Detection[]> {
  const byCategory: Record<string, Detection[]> = {};
  for (const d of detections) {
    (byCategory[d.category] ||= []).push(d);
  }
  return byCategory;
}

function filterByCategory(detections: Detection[], category: string | null): Detection[] {
  if (!category) return detections;
  return detections.filter((d) => d.category === category);
}

function countDetectionsInRange(
  detections: Detection[],
  startMs: number,
  endMs: number,
): number {
  return detections.filter((d) => d.t_ms >= startMs && d.t_ms < endMs).length;
}

function makeDetection(overrides: Partial<Detection> = {}): Detection {
  return {
    frame_idx: 0,
    t_ms: 0,
    category: "face",
    label: "person",
    confidence: 0.95,
    bbox_norm: [0.1, 0.1, 0.1, 0.1],
    from_cache: false,
    ...overrides,
  };
}

describe("groupByCategory", () => {
  it("groups detections by category", () => {
    const dets = [
      makeDetection({ category: "face", t_ms: 100 }),
      makeDetection({ category: "logo", t_ms: 200 }),
      makeDetection({ category: "face", t_ms: 300 }),
    ];
    const result = groupByCategory(dets);
    expect(Object.keys(result)).toEqual(["face", "logo"]);
    expect(result["face"]).toHaveLength(2);
    expect(result["logo"]).toHaveLength(1);
  });

  it("returns empty object for empty input", () => {
    expect(groupByCategory([])).toEqual({});
  });
});

describe("filterByCategory", () => {
  const dets = [
    makeDetection({ category: "face", t_ms: 100 }),
    makeDetection({ category: "logo", t_ms: 200 }),
    makeDetection({ category: "face", t_ms: 300 }),
  ];

  it("returns all when category is null", () => {
    expect(filterByCategory(dets, null)).toHaveLength(3);
  });

  it("filters to specified category", () => {
    expect(filterByCategory(dets, "face")).toHaveLength(2);
    expect(filterByCategory(dets, "logo")).toHaveLength(1);
  });

  it("returns empty for non-existent category", () => {
    expect(filterByCategory(dets, "card_object")).toHaveLength(0);
  });
});

describe("countDetectionsInRange", () => {
  const dets = [
    makeDetection({ t_ms: 1000 }),
    makeDetection({ t_ms: 2000 }),
    makeDetection({ t_ms: 3000 }),
    makeDetection({ t_ms: 5000 }),
  ];

  it("counts detections within time range", () => {
    expect(countDetectionsInRange(dets, 1000, 4000)).toBe(3);
  });

  it("start is inclusive, end is exclusive", () => {
    expect(countDetectionsInRange(dets, 1000, 2000)).toBe(1);
    expect(countDetectionsInRange(dets, 2000, 3000)).toBe(1);
  });

  it("returns 0 for empty range", () => {
    expect(countDetectionsInRange(dets, 10000, 20000)).toBe(0);
  });

  it("returns 0 for empty detections", () => {
    expect(countDetectionsInRange([], 0, 10000)).toBe(0);
  });
});
