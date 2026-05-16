// ============================================================================
// Left-rail skeleton list for the auto-shorts loading screen. Shows N vertical
// 9:16 placeholders matching the eventual count of generated shorts so the
// operator gets immediate feedback on how many clips are coming. Pure
// presentational — caller passes ``count``; no data hooks.
// ============================================================================

"use client";

import { cn } from "@/lib/utils";

interface Props {
  /** Total shorts being generated (sourced from ScanOrderStatusResponse.children_total). */
  count: number;
  className?: string;
}

export function LoadingShortsSkeleton({ count, className }: Props) {
  // children_total is degenerate (0) before fan-out lands. Render the header
  // with the literal count so the UI doesn't lie ("생성된 쇼츠 3개" while
  // count is actually 0). Skeleton boxes only render when count > 0.
  const safeCount = Math.max(0, Math.floor(count));

  return (
    <aside
      className={cn("flex flex-col gap-3", className)}
      data-testid="loading-shorts-skeleton"
    >
      <h2 className="text-sm font-semibold text-gray-800">
        생성된 쇼츠 <span className="text-gray-500">{safeCount}개</span>
      </h2>
      {safeCount > 0 ? (
        <div className="flex flex-col gap-3">
          {Array.from({ length: safeCount }, (_, i) => (
            <div
              key={i}
              className="aspect-[9/16] w-full animate-pulse rounded-lg bg-gray-200"
              data-testid="loading-shorts-skeleton-card"
            />
          ))}
        </div>
      ) : null}
    </aside>
  );
}
