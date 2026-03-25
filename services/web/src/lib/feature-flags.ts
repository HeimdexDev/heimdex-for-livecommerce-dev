/**
 * Feature flags for the Heimdex livecommerce platform.
 *
 * Toggle features on/off without code changes to the consuming components.
 * Components import FEATURES and gate their rendering — no prop drilling.
 *
 * To enable a feature: change the value to `true` and redeploy.
 */
export const FEATURES = {
  /** Display product/keyword tags on scenes, videos, and search filters. */
  TAGS_ENABLED: false,
} as const;
