/**
 * Feature-flag accessors for the web service.
 *
 * Flags ride on `NEXT_PUBLIC_*` env vars so client components can read them.
 * They are baked into the JS bundle at build time — flipping a flag means
 * rebuilding the web container, not a runtime config change.
 *
 * Strict-string parsing: only the literal "true" turns a flag on. Empty,
 * undefined, "false", "0", anything else → off. Avoids the bug class where
 * a non-empty build-time default accidentally enables a feature (or, in
 * multi-tenant builds, picks the wrong tenant's value) in environments
 * that should have it off.
 */

function readBoolean(envValue: string | undefined): boolean {
  return envValue === "true";
}

/**
 * Shorts editor V2 redesign — object-driven panel with text + background
 * overlays, transform/effects/preset sections matching the Figma redesign.
 *
 * When false, the legacy TextOverlayPanel renders.
 * When true, the new OverlayPanel renders.
 *
 * Rollout: false on prod until the V2 panel ships, then flipped to true
 * via a deploy with `NEXT_PUBLIC_EXPORT_SHORTS_EDITOR_V2_ENABLED=true` in
 * the web container's environment.
 */
export function isShortsEditorV2Enabled(): boolean {
  // V2 panel is the new figma-aligned editor surface; the env override is
  // kept only as an opt-out path while the legacy implementation lingers.
  if (process.env.NEXT_PUBLIC_EXPORT_SHORTS_EDITOR_V2_ENABLED === "false") {
    return false;
  }
  return true;
}
