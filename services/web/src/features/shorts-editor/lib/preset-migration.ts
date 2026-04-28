/**
 * One-time localStorage → backend preset migration.
 *
 * V1 stored named-style presets in localStorage at `heimdex:subtitle-presets`.
 * V2 stores them in the API at `/api/shorts/presets`. On the first V2 panel
 * mount per-browser, we POST each legacy entry, mark a "migrated" flag, and
 * clear the legacy key.
 *
 * Idempotency contract:
 * - Skip entirely if `heimdex:subtitle-presets-migrated=true`.
 * - Skip if no legacy entries exist (still set the flag so we don't read
 *   localStorage on every mount).
 * - On per-preset failure (e.g. 409 name conflict, transient 5xx), log,
 *   skip that entry, continue with the rest.
 * - The flag is set even on partial failure — we don't want to retry the
 *   same already-migrated rows forever. The legacy key is cleared ONLY on
 *   complete success so partial-failure history is recoverable from
 *   localStorage if a user reports loss.
 */

import { createPreset } from "@/lib/api/subtitle-presets";

const LEGACY_KEY = "heimdex:subtitle-presets";
const MIGRATED_FLAG_KEY = "heimdex:subtitle-presets-migrated";

type TokenGetter = () => Promise<string | null>;

interface LegacySubtitleStyle {
  fontFamily: string;
  fontSizePx: number;
  fontColor: string;
  fontWeight: number;
  positionX: number; // dropped — presets store style only
  positionY: number;
  backgroundColor: string | null;
  backgroundOpacity: number;
}

interface LegacyPreset {
  id: string;
  name: string;
  style: LegacySubtitleStyle;
  createdAt: number;
}

export interface MigrationResult {
  migrated: number;
  skipped: number;
  alreadyMigrated: boolean;
  noLegacyEntries: boolean;
}

const EMPTY_RESULT: MigrationResult = {
  migrated: 0,
  skipped: 0,
  alreadyMigrated: false,
  noLegacyEntries: true,
};

function readLegacy(): LegacyPreset[] {
  try {
    const raw = localStorage.getItem(LEGACY_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as LegacyPreset[]) : [];
  } catch {
    return [];
  }
}

/**
 * Map a V1 preset to the V2 createPreset payload.
 *
 * Notable choices:
 * - `kind: "text"` always — V1 had no background overlays.
 * - `is_shared: false` — preserve user's privacy expectation; they can opt
 *   in via the share toggle after migration.
 * - `text` is intentionally NOT in style_json. mergeTextStyle in usePresets
 *   uses the target overlay's text when the key is missing, which is what
 *   we want for migrated presets (V1 never bound text to presets either).
 * - V1 `backgroundColor` / `backgroundOpacity` map to V2 `highlight_color` /
 *   `highlight_opacity` — same text-fitted-pill semantics.
 */
export function legacyToCreatePayload(p: LegacyPreset): {
  name: string;
  kind: "text";
  style_json: Record<string, unknown>;
  is_shared: boolean;
} {
  return {
    name: p.name,
    kind: "text",
    is_shared: false,
    style_json: {
      font_family: p.style.fontFamily,
      font_size_px: p.style.fontSizePx,
      font_color: p.style.fontColor,
      font_weight: p.style.fontWeight,
      italic: false,
      underline: false,
      text_align: "center",
      line_height: 1.3,
      letter_spacing: 0,
      highlight_color: p.style.backgroundColor,
      highlight_padding_px: 8,
      highlight_opacity: p.style.backgroundOpacity,
      effects: { opacity: 1.0, stroke: null, shadow: null },
    },
  };
}

export async function runOneTimePresetMigration(
  getToken: TokenGetter,
): Promise<MigrationResult> {
  if (typeof window === "undefined") return EMPTY_RESULT;

  if (localStorage.getItem(MIGRATED_FLAG_KEY) === "true") {
    return { ...EMPTY_RESULT, alreadyMigrated: true };
  }

  const legacy = readLegacy();
  if (legacy.length === 0) {
    localStorage.setItem(MIGRATED_FLAG_KEY, "true");
    return EMPTY_RESULT;
  }

  let migrated = 0;
  let skipped = 0;
  for (const p of legacy) {
    try {
      await createPreset(legacyToCreatePayload(p), getToken);
      migrated++;
    } catch (err) {
      // 409 (duplicate name across users in same org isn't possible — preset
      // names are scoped per user — but a second tab could race the migration;
      // 5xx and offline also land here). Skip + continue.
      // eslint-disable-next-line no-console
      console.warn("preset-migration: skipped", p.name, err);
      skipped++;
    }
  }

  localStorage.setItem(MIGRATED_FLAG_KEY, "true");
  if (skipped === 0) {
    localStorage.removeItem(LEGACY_KEY);
  }
  return {
    migrated,
    skipped,
    alreadyMigrated: false,
    noLegacyEntries: false,
  };
}

/** Test-only — reset the migrated flag + restore legacy entries. */
export function _resetMigrationStateForTests(): void {
  if (typeof window === "undefined") return;
  localStorage.removeItem(MIGRATED_FLAG_KEY);
}
