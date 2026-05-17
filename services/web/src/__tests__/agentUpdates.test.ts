import { describe, expect, it } from "vitest";
import {
  isValidPlatform,
  parseManifest,
  toPublicManifest,
} from "@/lib/agentUpdates";

// ---------------------------------------------------------------------------
// Sample fixtures
// ---------------------------------------------------------------------------

const VALID_MANIFEST = {
  version: "0.3.0",
  release_date: "2026-02-15",
  release_notes: "Added face clustering",
  downloads: {
    "darwin-arm64": {
      url: "https://updates.heimdex.co/agent/0.3.0/HeimdexAgent-0.3.0-arm64.dmg",
      sha256: "abc123",
      size_bytes: 21000000,
    },
    "darwin-amd64": {
      url: "https://updates.heimdex.co/agent/0.3.0/HeimdexAgent-0.3.0-amd64.dmg",
      sha256: "def456",
      size_bytes: 22000000,
    },
    "windows-amd64": {
      url: "https://updates.heimdex.co/agent/0.3.0/HeimdexAgent-0.3.0-windows-amd64.zip",
      sha256: "ghi789",
      size_bytes: 20000000,
    },
  },
  min_version: "0.1.0",
};

// ---------------------------------------------------------------------------
// isValidPlatform
// ---------------------------------------------------------------------------

describe("isValidPlatform", () => {
  it("accepts darwin-arm64", () => {
    expect(isValidPlatform("darwin-arm64")).toBe(true);
  });

  it("accepts darwin-amd64", () => {
    expect(isValidPlatform("darwin-amd64")).toBe(true);
  });

  it("accepts windows-amd64", () => {
    expect(isValidPlatform("windows-amd64")).toBe(true);
  });

  it("rejects linux-amd64", () => {
    expect(isValidPlatform("linux-amd64")).toBe(false);
  });

  it("rejects empty string", () => {
    expect(isValidPlatform("")).toBe(false);
  });

  it("rejects random string", () => {
    expect(isValidPlatform("foobar")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// parseManifest
// ---------------------------------------------------------------------------

describe("parseManifest", () => {
  it("parses a valid manifest", () => {
    const m = parseManifest(VALID_MANIFEST);
    expect(m.version).toBe("0.3.0");
    expect(m.release_date).toBe("2026-02-15");
    expect(m.release_notes).toBe("Added face clustering");
    expect(m.min_version).toBe("0.1.0");
    expect(Object.keys(m.downloads)).toHaveLength(3);
    expect(m.downloads["darwin-arm64"].url).toContain("arm64.dmg");
    expect(m.downloads["darwin-arm64"].sha256).toBe("abc123");
    expect(m.downloads["darwin-arm64"].size_bytes).toBe(21000000);
  });

  it("parses manifest with only one platform", () => {
    const m = parseManifest({
      version: "1.0.0",
      downloads: {
        "darwin-arm64": {
          url: "https://example.com/a.dmg",
          sha256: "aaa",
          size_bytes: 100,
        },
      },
    });
    expect(m.version).toBe("1.0.0");
    expect(Object.keys(m.downloads)).toHaveLength(1);
  });

  it("ignores unknown platforms", () => {
    const m = parseManifest({
      version: "1.0.0",
      downloads: {
        "linux-amd64": {
          url: "https://example.com/linux",
          sha256: "xxx",
          size_bytes: 100,
        },
        "darwin-arm64": {
          url: "https://example.com/a.dmg",
          sha256: "aaa",
          size_bytes: 100,
        },
      },
    });
    expect(Object.keys(m.downloads)).toHaveLength(1);
    expect(m.downloads["darwin-arm64"]).toBeDefined();
  });

  it("skips download entries with missing fields", () => {
    const m = parseManifest({
      version: "1.0.0",
      downloads: {
        "darwin-arm64": { url: "https://example.com/a.dmg" }, // missing sha256, size_bytes
        "windows-amd64": {
          url: "https://example.com/w.zip",
          sha256: "bbb",
          size_bytes: 200,
        },
      },
    });
    expect(Object.keys(m.downloads)).toHaveLength(1);
    expect(m.downloads["windows-amd64"]).toBeDefined();
  });

  it("treats optional fields as undefined when absent", () => {
    const m = parseManifest({
      version: "1.0.0",
      downloads: {
        "darwin-arm64": {
          url: "https://example.com/a.dmg",
          sha256: "aaa",
          size_bytes: 100,
        },
      },
    });
    expect(m.release_date).toBeUndefined();
    expect(m.release_notes).toBeUndefined();
    expect(m.min_version).toBeUndefined();
  });

  it("throws on non-object input", () => {
    expect(() => parseManifest("not an object")).toThrow(
      "Manifest must be a JSON object",
    );
  });

  it("throws on null input", () => {
    expect(() => parseManifest(null)).toThrow(
      "Manifest must be a JSON object",
    );
  });

  it("throws when version is missing", () => {
    expect(() => parseManifest({ downloads: {} })).toThrow(
      "Manifest missing required field: version",
    );
  });

  it("throws when downloads is missing", () => {
    expect(() => parseManifest({ version: "1.0.0" })).toThrow(
      "Manifest missing required field: downloads",
    );
  });

  it("throws when no valid download entries exist", () => {
    expect(() =>
      parseManifest({
        version: "1.0.0",
        downloads: {
          "linux-amd64": {
            url: "https://example.com",
            sha256: "x",
            size_bytes: 1,
          },
        },
      }),
    ).toThrow("Manifest has no valid download entries");
  });
});

// ---------------------------------------------------------------------------
// toPublicManifest
// ---------------------------------------------------------------------------

describe("toPublicManifest", () => {
  it("strips download URLs", () => {
    const m = parseManifest(VALID_MANIFEST);
    const pub = toPublicManifest(m);

    expect(pub.version).toBe("0.3.0");
    expect(pub.platforms).toContain("darwin-arm64");
    expect(pub.platforms).toContain("darwin-amd64");
    expect(pub.platforms).toContain("windows-amd64");

    // Public manifest should NOT contain url
    const darwinEntry = pub.downloads["darwin-arm64"];
    expect(darwinEntry.sha256).toBe("abc123");
    expect(darwinEntry.size_bytes).toBe(21000000);
    expect((darwinEntry as Record<string, unknown>).url).toBeUndefined();
  });

  it("preserves optional fields", () => {
    const m = parseManifest(VALID_MANIFEST);
    const pub = toPublicManifest(m);
    expect(pub.release_date).toBe("2026-02-15");
    expect(pub.release_notes).toBe("Added face clustering");
  });
});
