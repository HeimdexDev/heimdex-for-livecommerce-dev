import { describe, expect, it, beforeEach } from "vitest";
import {
  getSnapshot,
  setData,
  setScrollY,
  clearNamespace,
  _resetAllSnapshots,
} from "@/lib/back-nav-cache";

beforeEach(() => {
  _resetAllSnapshots();
});

describe("back-nav-cache", () => {
  it("returns null when namespace empty", () => {
    expect(getSnapshot("browse", "k1")).toBeNull();
  });

  it("returns data + scroll for matching key", () => {
    setData("browse", "k1", { videos: [{ id: "a" }] });
    setScrollY("browse", "k1", 420);
    const snap = getSnapshot<{ videos: { id: string }[] }>("browse", "k1");
    expect(snap?.data?.videos).toEqual([{ id: "a" }]);
    expect(snap?.scrollY).toBe(420);
  });

  it("returns null when key changes — stale entry is dropped on next write", () => {
    setData("browse", "k1", { videos: [{ id: "a" }] });
    expect(getSnapshot("browse", "k2")).toBeNull();
    // Writing under a new key replaces the old one wholesale.
    setData("browse", "k2", { videos: [{ id: "b" }] });
    expect(getSnapshot("browse", "k1")).toBeNull();
    expect(getSnapshot<{ videos: { id: string }[] }>("browse", "k2")?.data?.videos).toEqual([
      { id: "b" },
    ]);
  });

  it("scrollY updates merge with existing data under same key", () => {
    setData("browse", "k1", { videos: [{ id: "a" }] });
    setScrollY("browse", "k1", 100);
    setScrollY("browse", "k1", 200);
    const snap = getSnapshot<{ videos: { id: string }[] }>("browse", "k1");
    expect(snap?.data?.videos).toEqual([{ id: "a" }]);
    expect(snap?.scrollY).toBe(200);
  });

  it("isolates namespaces", () => {
    setData("browse", "k1", { v: 1 });
    setData("search", "k1", { v: 2 });
    expect(getSnapshot<{ v: number }>("browse", "k1")?.data?.v).toBe(1);
    expect(getSnapshot<{ v: number }>("search", "k1")?.data?.v).toBe(2);
  });

  it("clearNamespace drops only that namespace", () => {
    setData("browse", "k1", { v: 1 });
    setData("search", "k1", { v: 2 });
    clearNamespace("browse");
    expect(getSnapshot("browse", "k1")).toBeNull();
    expect(getSnapshot<{ v: number }>("search", "k1")?.data?.v).toBe(2);
  });
});
