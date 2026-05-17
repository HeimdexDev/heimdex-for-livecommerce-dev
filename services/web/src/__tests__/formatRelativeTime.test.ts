import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";

/** Format ISO 8601 timestamp to Korean relative time string */
function formatRelativeTime(isoTimestamp: string | null | undefined): string | null {
  if (!isoTimestamp) return null;
  const diffMs = Date.now() - new Date(isoTimestamp).getTime();
  const diffMins = Math.floor(diffMs / 60000);
  if (diffMins < 1) return "방금 전";
  if (diffMins < 60) return `${diffMins}분 전`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}시간 전`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 30) return `${diffDays}일 전`;
  const diffMonths = Math.floor(diffDays / 30);
  return `${diffMonths}개월 전`;
}

describe("formatRelativeTime", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-03-15T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns null for null input", () => {
    expect(formatRelativeTime(null)).toBeNull();
  });

  it("returns null for undefined input", () => {
    expect(formatRelativeTime(undefined)).toBeNull();
  });

  it("returns '방금 전' for timestamps less than 1 minute old", () => {
    const now = new Date("2026-03-15T12:00:00Z");
    const thirtySecondsAgo = new Date(now.getTime() - 30 * 1000).toISOString();
    expect(formatRelativeTime(thirtySecondsAgo)).toBe("방금 전");
  });

  it("returns correct minute format for timestamps 1-59 minutes old", () => {
    const now = new Date("2026-03-15T12:00:00Z");
    const fiveMinutesAgo = new Date(now.getTime() - 5 * 60 * 1000).toISOString();
    expect(formatRelativeTime(fiveMinutesAgo)).toBe("5분 전");

    const fiftyNineMinutesAgo = new Date(now.getTime() - 59 * 60 * 1000).toISOString();
    expect(formatRelativeTime(fiftyNineMinutesAgo)).toBe("59분 전");
  });

  it("returns correct hour format for timestamps 1-23 hours old", () => {
    const now = new Date("2026-03-15T12:00:00Z");
    const twoHoursAgo = new Date(now.getTime() - 2 * 60 * 60 * 1000).toISOString();
    expect(formatRelativeTime(twoHoursAgo)).toBe("2시간 전");

    const twentyThreeHoursAgo = new Date(now.getTime() - 23 * 60 * 60 * 1000).toISOString();
    expect(formatRelativeTime(twentyThreeHoursAgo)).toBe("23시간 전");
  });

  it("returns correct day format for timestamps 1-29 days old", () => {
    const now = new Date("2026-03-15T12:00:00Z");
    const threeDaysAgo = new Date(now.getTime() - 3 * 24 * 60 * 60 * 1000).toISOString();
    expect(formatRelativeTime(threeDaysAgo)).toBe("3일 전");

    const twentyNineDaysAgo = new Date(now.getTime() - 29 * 24 * 60 * 60 * 1000).toISOString();
    expect(formatRelativeTime(twentyNineDaysAgo)).toBe("29일 전");
  });

  it("returns correct month format for timestamps 30+ days old", () => {
    const now = new Date("2026-03-15T12:00:00Z");
    const twoMonthsAgo = new Date(now.getTime() - 60 * 24 * 60 * 60 * 1000).toISOString();
    expect(formatRelativeTime(twoMonthsAgo)).toBe("2개월 전");

    const sixMonthsAgo = new Date(now.getTime() - 180 * 24 * 60 * 60 * 1000).toISOString();
    expect(formatRelativeTime(sixMonthsAgo)).toBe("6개월 전");
  });

  it("handles boundary between minutes and hours correctly", () => {
    const now = new Date("2026-03-15T12:00:00Z");
    const sixtyMinutesAgo = new Date(now.getTime() - 60 * 60 * 1000).toISOString();
    expect(formatRelativeTime(sixtyMinutesAgo)).toBe("1시간 전");
  });

  it("handles boundary between hours and days correctly", () => {
    const now = new Date("2026-03-15T12:00:00Z");
    const twentyFourHoursAgo = new Date(now.getTime() - 24 * 60 * 60 * 1000).toISOString();
    expect(formatRelativeTime(twentyFourHoursAgo)).toBe("1일 전");
  });

  it("handles boundary between days and months correctly", () => {
    const now = new Date("2026-03-15T12:00:00Z");
    const thirtyDaysAgo = new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000).toISOString();
    expect(formatRelativeTime(thirtyDaysAgo)).toBe("1개월 전");
  });
});
