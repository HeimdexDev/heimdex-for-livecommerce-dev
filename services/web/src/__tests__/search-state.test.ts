import { describe, expect, it } from "vitest";
import {
  serializeSearchState,
  deserializeSearchState,
  hasSearchParams,
  ALL_SOURCES,
  type DashboardSearchState,
} from "@/lib/search-state";

function defaults(): DashboardSearchState {
  return {
    query: "",
    searchMode: "lexical",
    groupBy: "scene",
    sortBy: "latest",
    contentType: "all",
    referenceMode: false,
    currentPage: 1,
    sourceFilters: new Set(ALL_SOURCES),
    dateStart: null,
    dateEnd: null,
  };
}

describe("serializeSearchState", () => {
  it("produces empty params for default state", () => {
    const params = serializeSearchState(defaults());
    expect(params.toString()).toBe("");
  });

  it("serializes query", () => {
    const state = { ...defaults(), query: "라이브커머스" };
    const params = serializeSearchState(state);
    expect(params.get("q")).toBe("라이브커머스");
  });

  it("serializes non-default searchMode", () => {
    const state = { ...defaults(), searchMode: "semantic" as const };
    const params = serializeSearchState(state);
    expect(params.get("mode")).toBe("semantic");
  });

  it("omits default searchMode", () => {
    const params = serializeSearchState(defaults());
    expect(params.has("mode")).toBe(false);
  });

  it("serializes groupBy when not default", () => {
    const state = { ...defaults(), groupBy: "video" as const };
    const params = serializeSearchState(state);
    expect(params.get("group")).toBe("video");
  });

  it("serializes sortBy when not default", () => {
    const state = { ...defaults(), sortBy: "alpha_asc" as const };
    const params = serializeSearchState(state);
    expect(params.get("sort")).toBe("alpha_asc");
  });

  it("serializes relevance sortBy", () => {
    const state = { ...defaults(), sortBy: "relevance" as const };
    const params = serializeSearchState(state);
    expect(params.get("sort")).toBe("relevance");
  });

  it("serializes page > 1", () => {
    const state = { ...defaults(), currentPage: 3 };
    const params = serializeSearchState(state);
    expect(params.get("page")).toBe("3");
  });

  it("omits page 1", () => {
    const params = serializeSearchState(defaults());
    expect(params.has("page")).toBe(false);
  });

  it("serializes partial source filters", () => {
    const state = {
      ...defaults(),
      sourceFilters: new Set(["gdrive", "local"] as const),
    };
    const params = serializeSearchState(state);
    expect(params.get("sources")).toBe("gdrive,local");
  });

  it("omits sources when all selected", () => {
    const params = serializeSearchState(defaults());
    expect(params.has("sources")).toBe(false);
  });

  it("serializes date range", () => {
    const state = {
      ...defaults(),
      dateStart: new Date("2026-01-15T00:00:00"),
      dateEnd: new Date("2026-03-01T00:00:00"),
    };
    const params = serializeSearchState(state);
    expect(params.get("ds")).toBe("2026-01-15");
    expect(params.get("de")).toBe("2026-03-01");
  });

  it("omits null dates", () => {
    const params = serializeSearchState(defaults());
    expect(params.has("ds")).toBe(false);
    expect(params.has("de")).toBe(false);
  });
});

describe("deserializeSearchState", () => {
  it("returns defaults for empty params", () => {
    const state = deserializeSearchState(new URLSearchParams());
    expect(state.query).toBe("");
    expect(state.searchMode).toBe("lexical");
    expect(state.groupBy).toBe("scene");
    expect(state.sortBy).toBe("latest");
    expect(state.currentPage).toBe(1);
    expect(state.sourceFilters).toEqual(new Set(ALL_SOURCES));
    expect(state.dateStart).toBeNull();
    expect(state.dateEnd).toBeNull();
  });

  it("parses query", () => {
    const params = new URLSearchParams("q=test+query");
    const state = deserializeSearchState(params);
    expect(state.query).toBe("test query");
  });

  it("parses valid searchMode", () => {
    const state = deserializeSearchState(new URLSearchParams("mode=semantic"));
    expect(state.searchMode).toBe("semantic");
  });

  it("ignores invalid searchMode", () => {
    const state = deserializeSearchState(new URLSearchParams("mode=invalid"));
    expect(state.searchMode).toBe("lexical");
  });

  it("parses valid groupBy", () => {
    const state = deserializeSearchState(new URLSearchParams("group=video"));
    expect(state.groupBy).toBe("video");
  });

  it("ignores invalid groupBy", () => {
    const state = deserializeSearchState(new URLSearchParams("group=banana"));
    expect(state.groupBy).toBe("scene");
  });

  it("parses valid sortBy", () => {
    const state = deserializeSearchState(new URLSearchParams("sort=alpha_desc"));
    expect(state.sortBy).toBe("alpha_desc");
  });

  it("parses relevance sortBy", () => {
    const state = deserializeSearchState(new URLSearchParams("sort=relevance"));
    expect(state.sortBy).toBe("relevance");
  });

  it("ignores invalid sortBy", () => {
    const state = deserializeSearchState(new URLSearchParams("sort=random"));
    expect(state.sortBy).toBe("latest");
  });

  it("parses valid page", () => {
    const state = deserializeSearchState(new URLSearchParams("page=5"));
    expect(state.currentPage).toBe(5);
  });

  it("ignores non-numeric page", () => {
    const state = deserializeSearchState(new URLSearchParams("page=abc"));
    expect(state.currentPage).toBe(1);
  });

  it("ignores negative page", () => {
    const state = deserializeSearchState(new URLSearchParams("page=-2"));
    expect(state.currentPage).toBe(1);
  });

  it("ignores zero page", () => {
    const state = deserializeSearchState(new URLSearchParams("page=0"));
    expect(state.currentPage).toBe(1);
  });

  it("parses source filters", () => {
    const state = deserializeSearchState(
      new URLSearchParams("sources=gdrive,local"),
    );
    expect(state.sourceFilters).toEqual(new Set(["gdrive", "local"]));
  });

  it("ignores invalid source types", () => {
    const state = deserializeSearchState(
      new URLSearchParams("sources=gdrive,invalid,local"),
    );
    expect(state.sourceFilters).toEqual(new Set(["gdrive", "local"]));
  });

  it("falls back to all sources for fully invalid sources param", () => {
    const state = deserializeSearchState(
      new URLSearchParams("sources=invalid"),
    );
    expect(state.sourceFilters).toEqual(new Set(ALL_SOURCES));
  });

  it("parses date range", () => {
    const state = deserializeSearchState(
      new URLSearchParams("ds=2026-01-15&de=2026-03-01"),
    );
    expect(state.dateStart).toEqual(new Date("2026-01-15T00:00:00"));
    expect(state.dateEnd).toEqual(new Date("2026-03-01T00:00:00"));
  });

  it("ignores malformed dates", () => {
    const state = deserializeSearchState(
      new URLSearchParams("ds=not-a-date&de=2026-13-01"),
    );
    expect(state.dateStart).toBeNull();
    expect(state.dateEnd).toBeNull();
  });
});

describe("round-trip", () => {
  it("serialize → deserialize preserves full state", () => {
    const original: DashboardSearchState = {
      query: "Korean 라이브",
      searchMode: "semantic",
      groupBy: "video",
      sortBy: "alpha_desc",
      contentType: "image",
      referenceMode: false,
      currentPage: 3,
      sourceFilters: new Set(["gdrive"] as const),
      dateStart: new Date("2026-02-01T00:00:00"),
      dateEnd: new Date("2026-02-28T00:00:00"),
    };

    const params = serializeSearchState(original);
    const restored = deserializeSearchState(params);

    expect(restored.query).toBe(original.query);
    expect(restored.searchMode).toBe(original.searchMode);
    expect(restored.groupBy).toBe(original.groupBy);
    expect(restored.sortBy).toBe(original.sortBy);
    expect(restored.contentType).toBe(original.contentType);
    expect(restored.currentPage).toBe(original.currentPage);
    expect(restored.sourceFilters).toEqual(original.sourceFilters);
    expect(restored.dateStart).toEqual(original.dateStart);
    expect(restored.dateEnd).toEqual(original.dateEnd);
  });

  it("serialize → deserialize preserves relevance sort", () => {
    const original: DashboardSearchState = {
      query: "테스트",
      searchMode: "lexical",
      groupBy: "scene",
      sortBy: "relevance",
      contentType: "all",
      referenceMode: false,
      currentPage: 1,
      sourceFilters: new Set(ALL_SOURCES),
      dateStart: null,
      dateEnd: null,
    };

    const params = serializeSearchState(original);
    const restored = deserializeSearchState(params);
    expect(restored.sortBy).toBe("relevance");
    expect(restored.query).toBe("테스트");
  });

  it("serialize → deserialize preserves defaults", () => {
    const original = defaults();
    const params = serializeSearchState(original);
    const restored = deserializeSearchState(params);

    expect(restored.query).toBe("");
    expect(restored.searchMode).toBe("lexical");
    expect(restored.groupBy).toBe("scene");
    expect(restored.sortBy).toBe("latest");
    expect(restored.currentPage).toBe(1);
    expect(restored.sourceFilters).toEqual(new Set(ALL_SOURCES));
    expect(restored.dateStart).toBeNull();
    expect(restored.dateEnd).toBeNull();
  });
});

describe("contentType serialization", () => {
  it("omits default contentType (all)", () => {
    const params = serializeSearchState(defaults());
    expect(params.has("type")).toBe(false);
  });

  it("serializes video contentType", () => {
    const state = { ...defaults(), contentType: "video" as const };
    const params = serializeSearchState(state);
    expect(params.get("type")).toBe("video");
  });

  it("serializes image contentType", () => {
    const state = { ...defaults(), contentType: "image" as const };
    const params = serializeSearchState(state);
    expect(params.get("type")).toBe("image");
  });

  it("deserializes valid contentType", () => {
    const state = deserializeSearchState(new URLSearchParams("type=image"));
    expect(state.contentType).toBe("image");
  });

  it("deserializes video contentType", () => {
    const state = deserializeSearchState(new URLSearchParams("type=video"));
    expect(state.contentType).toBe("video");
  });

  it("defaults to all for missing type param", () => {
    const state = deserializeSearchState(new URLSearchParams());
    expect(state.contentType).toBe("all");
  });

  it("defaults to all for invalid type param", () => {
    const state = deserializeSearchState(new URLSearchParams("type=invalid"));
    expect(state.contentType).toBe("all");
  });

  it("round-trips contentType", () => {
    const original = { ...defaults(), contentType: "image" as const };
    const params = serializeSearchState(original);
    const restored = deserializeSearchState(params);
    expect(restored.contentType).toBe("image");
  });
});

describe("referenceMode serialization", () => {
  it("omits ref param when referenceMode is false", () => {
    const params = serializeSearchState(defaults());
    expect(params.has("ref")).toBe(false);
  });

  it("serializes ref=1 when referenceMode is true", () => {
    const state = { ...defaults(), referenceMode: true };
    const params = serializeSearchState(state);
    expect(params.get("ref")).toBe("1");
  });

  it("deserializes ref=1 as referenceMode true", () => {
    const state = deserializeSearchState(new URLSearchParams("ref=1"));
    expect(state.referenceMode).toBe(true);
  });

  it("defaults to false for missing ref param", () => {
    const state = deserializeSearchState(new URLSearchParams());
    expect(state.referenceMode).toBe(false);
  });

  it("defaults to false for invalid ref param", () => {
    const state = deserializeSearchState(new URLSearchParams("ref=invalid"));
    expect(state.referenceMode).toBe(false);
  });

  it("round-trips referenceMode", () => {
    const original = { ...defaults(), referenceMode: true };
    const params = serializeSearchState(original);
    const restored = deserializeSearchState(params);
    expect(restored.referenceMode).toBe(true);
  });
});

describe("hasSearchParams", () => {
  it("returns true when q param exists", () => {
    expect(hasSearchParams(new URLSearchParams("q=test"))).toBe(true);
  });

  it("returns false for empty params", () => {
    expect(hasSearchParams(new URLSearchParams())).toBe(false);
  });

  it("returns false for non-search params", () => {
    expect(hasSearchParams(new URLSearchParams("mode=semantic"))).toBe(false);
  });
});
