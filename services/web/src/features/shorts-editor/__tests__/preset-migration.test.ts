/**
 * Tests for the V1 → V2 preset migration.
 *
 * Mocks `createPreset` so we test the migration's idempotency + payload
 * shape, not the API client itself.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api/subtitle-presets", () => ({
  createPreset: vi.fn(),
}));

import { createPreset } from "@/lib/api/subtitle-presets";
import {
  _resetMigrationStateForTests,
  legacyToCreatePayload,
  runOneTimePresetMigration,
} from "../lib/preset-migration";

const LEGACY_KEY = "heimdex:subtitle-presets";
const MIGRATED_FLAG_KEY = "heimdex:subtitle-presets-migrated";

const mockGetToken = async () => "fake-token";

function legacyPresetFixture(overrides: Partial<{ name: string; backgroundColor: string | null }> = {}) {
  return {
    id: "preset_1",
    name: overrides.name ?? "헤드라인",
    style: {
      fontFamily: "Pretendard",
      fontSizePx: 36,
      fontColor: "#FFFFFF",
      fontWeight: 700,
      positionX: 0.5,
      positionY: 0.85,
      backgroundColor: overrides.backgroundColor ?? null,
      backgroundOpacity: 0.6,
    },
    createdAt: 1700000000000,
  };
}

beforeEach(() => {
  localStorage.clear();
  vi.clearAllMocks();
  _resetMigrationStateForTests();
});

afterEach(() => {
  localStorage.clear();
});

describe("legacyToCreatePayload", () => {
  it("maps V1 SubtitleStyle → V2 PresetCreate without losing fields", () => {
    const payload = legacyToCreatePayload(
      legacyPresetFixture({ backgroundColor: "#000000" }),
    );

    expect(payload).toMatchObject({
      name: "헤드라인",
      kind: "text",
      is_shared: false,
    });
    expect(payload.style_json).toMatchObject({
      font_family: "Pretendard",
      font_size_px: 36,
      font_color: "#FFFFFF",
      font_weight: 700,
      italic: false,
      underline: false,
      text_align: "center",
      line_height: 1.3,
      letter_spacing: 0,
      highlight_color: "#000000",
      highlight_padding_px: 8,
      highlight_opacity: 0.6,
    });
    expect(payload.style_json["effects"]).toEqual({
      opacity: 1.0,
      stroke: null,
      shadow: null,
    });
  });

  it("does NOT include `text` in style_json (so apply preserves target text)", () => {
    const payload = legacyToCreatePayload(legacyPresetFixture());
    expect(payload.style_json).not.toHaveProperty("text");
  });

  it("maps null backgroundColor to null highlight_color", () => {
    const payload = legacyToCreatePayload(legacyPresetFixture({ backgroundColor: null }));
    expect(payload.style_json["highlight_color"]).toBeNull();
  });
});

describe("runOneTimePresetMigration", () => {
  it("returns alreadyMigrated when flag is set + does nothing", async () => {
    localStorage.setItem(MIGRATED_FLAG_KEY, "true");
    localStorage.setItem(LEGACY_KEY, JSON.stringify([legacyPresetFixture()]));

    const result = await runOneTimePresetMigration(mockGetToken);

    expect(result.alreadyMigrated).toBe(true);
    expect(result.migrated).toBe(0);
    expect(createPreset).not.toHaveBeenCalled();
    // Legacy key NOT cleared — we don't touch already-migrated state
    expect(localStorage.getItem(LEGACY_KEY)).not.toBeNull();
  });

  it("flags as migrated even when there are no legacy entries", async () => {
    const result = await runOneTimePresetMigration(mockGetToken);

    expect(result.migrated).toBe(0);
    expect(result.noLegacyEntries).toBe(true);
    expect(localStorage.getItem(MIGRATED_FLAG_KEY)).toBe("true");
    expect(createPreset).not.toHaveBeenCalled();
  });

  it("posts each legacy preset, sets flag, clears legacy on full success", async () => {
    const presets = [
      legacyPresetFixture({ name: "preset-A" }),
      legacyPresetFixture({ name: "preset-B" }),
      legacyPresetFixture({ name: "preset-C" }),
    ];
    localStorage.setItem(LEGACY_KEY, JSON.stringify(presets));
    vi.mocked(createPreset).mockResolvedValue({
      id: "id",
      org_id: "org",
      user_id: "user",
      name: "name",
      kind: "text",
      style_json: {},
      is_shared: false,
      is_owned: true,
      created_at: "x",
      updated_at: "x",
    });

    const result = await runOneTimePresetMigration(mockGetToken);

    expect(result.migrated).toBe(3);
    expect(result.skipped).toBe(0);
    expect(createPreset).toHaveBeenCalledTimes(3);
    expect(localStorage.getItem(MIGRATED_FLAG_KEY)).toBe("true");
    expect(localStorage.getItem(LEGACY_KEY)).toBeNull();
  });

  it("skips failed entries, sets flag, but KEEPS legacy on partial failure", async () => {
    const presets = [
      legacyPresetFixture({ name: "ok-1" }),
      legacyPresetFixture({ name: "boom" }),
      legacyPresetFixture({ name: "ok-2" }),
    ];
    localStorage.setItem(LEGACY_KEY, JSON.stringify(presets));
    vi.mocked(createPreset)
      .mockResolvedValueOnce({} as never)
      .mockRejectedValueOnce(new Error("server boom"))
      .mockResolvedValueOnce({} as never);

    const result = await runOneTimePresetMigration(mockGetToken);

    expect(result.migrated).toBe(2);
    expect(result.skipped).toBe(1);
    expect(localStorage.getItem(MIGRATED_FLAG_KEY)).toBe("true");
    // Legacy preserved for recovery investigation
    expect(localStorage.getItem(LEGACY_KEY)).not.toBeNull();
  });

  it("ignores garbage in legacy localStorage", async () => {
    localStorage.setItem(LEGACY_KEY, "not-json{");

    const result = await runOneTimePresetMigration(mockGetToken);

    expect(result.migrated).toBe(0);
    expect(result.noLegacyEntries).toBe(true);
    expect(localStorage.getItem(MIGRATED_FLAG_KEY)).toBe("true");
    expect(createPreset).not.toHaveBeenCalled();
  });
});
