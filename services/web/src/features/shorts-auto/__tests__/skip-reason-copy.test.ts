import { describe, expect, it } from "vitest";

import {
  skipReasonCopy,
  __SKIP_REASON_BASE_COPY_FOR_TESTS as BASE_COPY,
} from "../lib/skip-reason-copy";

describe("skipReasonCopy", () => {
  it("returns non-empty Korean copy for every known reason", () => {
    for (const reason of Object.keys(BASE_COPY)) {
      const copy = skipReasonCopy(reason);
      expect(copy.length).toBeGreaterThan(0);
      // Every copy string should contain Hangul characters.
      expect(copy).toMatch(/[\u3131-\uD79D]/);
    }
  });

  it("falls back for null/undefined reason", () => {
    expect(skipReasonCopy(null)).toMatch(/[\u3131-\uD79D]/);
    expect(skipReasonCopy(undefined)).toMatch(/[\u3131-\uD79D]/);
  });

  it("returns generic fallback for unknown reason", () => {
    const copy = skipReasonCopy("some_new_reason_not_in_enum");
    expect(copy).toMatch(/[\u3131-\uD79D]/);
    expect(copy).not.toContain("some_new_reason_not_in_enum");
  });

  it("uses product-mode override for no_candidate_scenes_after_filter", () => {
    const generic = skipReasonCopy("no_candidate_scenes_after_filter");
    const product = skipReasonCopy("no_candidate_scenes_after_filter", "product");
    expect(product).not.toBe(generic);
    expect(product).toContain("상품");
  });

  it("uses human-mode override for no_candidate_scenes_after_filter", () => {
    const generic = skipReasonCopy("no_candidate_scenes_after_filter");
    const human = skipReasonCopy("no_candidate_scenes_after_filter", "human");
    expect(human).not.toBe(generic);
    expect(human).toContain("인물");
  });

  it("falls through to base copy when mode override absent", () => {
    // `video_too_short` has no mode override
    expect(skipReasonCopy("video_too_short", "product")).toBe(
      skipReasonCopy("video_too_short"),
    );
  });
});
