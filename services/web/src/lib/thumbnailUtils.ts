/**
 * Thumbnail aspect ratio utilities.
 * 
 * Maps org-level aspect ratio settings to Tailwind CSS classes.
 * SceneThumbnail itself is aspect-agnostic (uses object-cover).
 * The parent container controls the aspect ratio.
 */

export type ThumbnailAspectRatio = "16:9" | "9:16";

/** Aspect ratio CSS class for thumbnail containers. */
export function getThumbnailAspectClass(ratio: ThumbnailAspectRatio): string {
  return ratio === "9:16" ? "aspect-[9/16]" : "aspect-video";
}

/** Grid column classes for dashboard cards (more cols for narrow vertical cards). */
export function getDashboardGridClass(ratio: ThumbnailAspectRatio): string {
  return ratio === "9:16"
    ? "grid-cols-3 sm:grid-cols-4 lg:grid-cols-5 xl:grid-cols-6"
    : "grid-cols-2 sm:grid-cols-3 lg:grid-cols-4";
}

/** Fixed dimensions for inline scene thumbnails (search results, video cards). */
export function getInlineThumbnailClass(ratio: ThumbnailAspectRatio): string {
  return ratio === "9:16" ? "w-14 h-24" : "w-32 h-20";
}

/** Fixed dimensions for small inline thumbnails (drawer scene list). */
export function getSmallThumbnailClass(ratio: ThumbnailAspectRatio): string {
  return ratio === "9:16" ? "w-10 h-16" : "w-20 h-14";
}

/** Fixed width for video detail page scene thumbnails. */
export function getDetailThumbnailClass(ratio: ThumbnailAspectRatio): string {
  return ratio === "9:16" ? "w-[120px]" : "w-[200px]";
}

/** Fixed dimensions for video card thumbnails (side-panel list view). */
export function getVideoCardThumbnailClass(ratio: ThumbnailAspectRatio): string {
  return ratio === "9:16" ? "w-16 h-28" : "w-28 h-20";
}

/** Drawer hero thumbnail height. */
export function getDrawerHeroClass(ratio: ThumbnailAspectRatio): string {
  return ratio === "9:16" ? "h-64" : "h-40";
}

/** Grid layout for person scene thumbnails (people tab). */
export function getPersonGridClass(ratio: ThumbnailAspectRatio): string {
  return ratio === "9:16" ? "grid-cols-4 gap-2" : "grid-cols-3 gap-3";
}
