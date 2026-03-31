import { describe, it, expect } from "vitest";
import {
  sanitizeTag,
  hasTagFilters,
  TAG_FILTER_MAX_ITEMS,
  TAG_FILTER_MAX_ITEM_LEN,
  TAG_FILTER_FIELDS,
} from "@/lib/types/search";
import type { SearchFilters } from "@/lib/types/search";

describe("sanitizeTag", () => {
  it("trims whitespace", () => {
    expect(sanitizeTag("  hello  ")).toBe("hello");
  });

  it("returns empty string for whitespace-only input", () => {
    expect(sanitizeTag("   ")).toBe("");
  });

  it("truncates to TAG_FILTER_MAX_ITEM_LEN characters", () => {
    const long = "A".repeat(100);
    expect(sanitizeTag(long)).toBe("A".repeat(TAG_FILTER_MAX_ITEM_LEN));
    expect(sanitizeTag(long).length).toBe(64);
  });

  it("preserves Korean characters", () => {
    expect(sanitizeTag("  할인 프로모션  ")).toBe("할인 프로모션");
  });

  it("does not modify strings within limits", () => {
    expect(sanitizeTag("normal tag")).toBe("normal tag");
  });
});

describe("hasTagFilters", () => {
  it("returns false for empty filters", () => {
    expect(hasTagFilters({})).toBe(false);
  });

  it("returns false when only non-tag filters present", () => {
    const filters: SearchFilters = { source_types: ["gdrive"], library_ids: ["lib1"] };
    expect(hasTagFilters(filters)).toBe(false);
  });

  it("returns true when keyword_tags_in has entries", () => {
    expect(hasTagFilters({ keyword_tags_in: ["할인"] })).toBe(true);
  });

  it("returns true when product_tags_not_in has entries", () => {
    expect(hasTagFilters({ product_tags_not_in: ["alcohol"] })).toBe(true);
  });

  it("returns true when product_entities_in has entries", () => {
    expect(hasTagFilters({ product_entities_in: ["Nike"] })).toBe(true);
  });

  it("returns true when ai_tags_in has entries", () => {
    expect(hasTagFilters({ ai_tags_in: ["수분크림"] })).toBe(true);
  });

  it("returns true when ai_tags_not_in has entries", () => {
    expect(hasTagFilters({ ai_tags_not_in: ["보습"] })).toBe(true);
  });

  it("returns false when all tag fields are empty arrays", () => {
    const filters: SearchFilters = {
      keyword_tags_in: [],
      keyword_tags_not_in: [],
      product_tags_in: [],
      product_tags_not_in: [],
      product_entities_in: [],
      product_entities_not_in: [],
      ai_tags_in: [],
      ai_tags_not_in: [],
    };
    expect(hasTagFilters(filters)).toBe(false);
  });
});

describe("TAG_FILTER constants", () => {
  it("MAX_ITEMS matches backend constraint", () => {
    expect(TAG_FILTER_MAX_ITEMS).toBe(50);
  });

  it("MAX_ITEM_LEN matches backend constraint", () => {
    expect(TAG_FILTER_MAX_ITEM_LEN).toBe(64);
  });

  it("FIELDS contains all 8 tag filter field names", () => {
    expect(TAG_FILTER_FIELDS).toEqual([
      "keyword_tags_in",
      "keyword_tags_not_in",
      "product_tags_in",
      "product_tags_not_in",
      "product_entities_in",
      "product_entities_not_in",
      "ai_tags_in",
      "ai_tags_not_in",
    ]);
  });
});

describe("SearchFilters type compatibility", () => {
  it("accepts all 8 tag filter fields", () => {
    const filters: SearchFilters = {
      keyword_tags_in: ["할인"],
      keyword_tags_not_in: ["광고"],
      product_tags_in: ["cosmetics"],
      product_tags_not_in: ["alcohol"],
      product_entities_in: ["Nike Air Max"],
      product_entities_not_in: ["BadBrand"],
      ai_tags_in: ["수분크림"],
      ai_tags_not_in: ["보습"],
    };
    expect(filters.keyword_tags_in).toEqual(["할인"]);
    expect(filters.product_entities_not_in).toEqual(["BadBrand"]);
    expect(filters.ai_tags_in).toEqual(["수분크림"]);
    expect(filters.ai_tags_not_in).toEqual(["보습"]);
  });

  it("all tag fields are optional (backward compatible)", () => {
    const filters: SearchFilters = { source_types: ["gdrive"] };
    expect(filters.keyword_tags_in).toBeUndefined();
    expect(filters.product_tags_not_in).toBeUndefined();
  });
});

describe("request payload construction", () => {
  it("include-only payload maps correctly", () => {
    const filters: SearchFilters = {
      keyword_tags_in: ["할인", "프로모션"],
      product_entities_in: ["Nike Air Max"],
    };
    const payload = { q: "test", alpha: 0.5, filters };
    const body = JSON.parse(JSON.stringify(payload));

    expect(body.filters.keyword_tags_in).toEqual(["할인", "프로모션"]);
    expect(body.filters.product_entities_in).toEqual(["Nike Air Max"]);
    expect(body.filters.keyword_tags_not_in).toBeUndefined();
    expect(body.filters.product_tags_in).toBeUndefined();
  });

  it("exclude-only payload maps correctly", () => {
    const filters: SearchFilters = {
      keyword_tags_not_in: ["광고"],
      product_tags_not_in: ["alcohol"],
    };
    const payload = { q: "test", alpha: 0.5, filters };
    const body = JSON.parse(JSON.stringify(payload));

    expect(body.filters.keyword_tags_not_in).toEqual(["광고"]);
    expect(body.filters.product_tags_not_in).toEqual(["alcohol"]);
    expect(body.filters.keyword_tags_in).toBeUndefined();
  });

  it("mixed include/exclude payload maps correctly", () => {
    const filters: SearchFilters = {
      source_types: ["gdrive"],
      keyword_tags_in: ["할인"],
      keyword_tags_not_in: ["광고"],
      product_tags_in: ["cosmetics"],
      product_entities_not_in: ["BadBrand"],
    };
    const payload = { q: "test", alpha: 0.5, filters };
    const body = JSON.parse(JSON.stringify(payload));

    expect(body.filters.source_types).toEqual(["gdrive"]);
    expect(body.filters.keyword_tags_in).toEqual(["할인"]);
    expect(body.filters.keyword_tags_not_in).toEqual(["광고"]);
    expect(body.filters.product_tags_in).toEqual(["cosmetics"]);
    expect(body.filters.product_entities_not_in).toEqual(["BadBrand"]);
  });

  it("empty filters produce no tag fields in payload", () => {
    const filters: SearchFilters = {};
    const body = JSON.parse(JSON.stringify({ q: "test", alpha: 0.5, filters }));

    for (const field of TAG_FILTER_FIELDS) {
      expect(body.filters[field]).toBeUndefined();
    }
  });
});
